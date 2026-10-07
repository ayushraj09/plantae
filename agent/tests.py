"""Human-in-the-loop tests. All LLM calls are mocked, so these cost no API credits.

Run with:  AGENT_CHECKPOINTER=memory python manage.py test agent
"""
import hashlib
import hmac
import json
import time
from importlib import import_module
from unittest import mock
from urllib.parse import urlencode

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Account
from agent.hitl import service
from agent.langgraph.agent import RouteDecision
from agent.langgraph.escalation import IntakeExtraction, detect_hard_triggers
from agent.models import ChatMessage, EscalationTicket, TicketEvent
from carts.models import CartItem
from category.models import Category
from orders.models import Order
from store.models import Product


def run_now(func_path, *args, **kwargs):
    """Stand-in for django-q's async_task: run the task inline (after commit, like the worker)."""
    module, name = func_path.rsplit(".", 1)
    getattr(import_module(module), name)(*args)


def route(name, category=None, sentiment="neutral"):
    return RouteDecision(route=name, escalation_category=category, sentiment=sentiment, confidence=0.9)


# Tests must never reach the real Slack workspace or send email, whatever .env contains.
@override_settings(SLACK_BOT_TOKEN="", SLACK_SIGNING_SECRET="", SLACK_ESCALATION_CHANNEL="", HITL_STAFF_EMAILS=[],
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class HitlTestBase(TestCase):
    def setUp(self):
        # Background tasks run inline; the two LLM calls in the escalation graph are stubbed.
        for target, kwargs in [
            ("django_q.tasks.async_task", {"side_effect": run_now}),
            ("agent.langgraph.escalation.summarize_ticket", {"return_value": "Customer wants a price match."}),
            ("agent.langgraph.escalation.compose_customer_reply",
             {"side_effect": lambda ticket, decision, result: f"REPLY[{decision['action']}]: {result}"}),
        ]:
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.user = Account.objects.create_user("Asha", "Rao", "asha", "asha@example.com", "pw", phone_number="9999999999")
        self.user.is_active = True
        self.user.save()
        self.staff = Account.objects.create_user("Sam", "Staff", "sam", "sam@example.com", "pw", phone_number="8888888888")
        self.staff.is_active = self.staff.is_staff = True
        self.staff.save()
        cat = Category.objects.create(category_name="Plants", slug="plants")
        self.product = Product.objects.create(product_name="Snake Plant", slug="snake-plant", price=400,
                                              stock=10, category=cat, description="Hardy")
        Product.objects.create(product_name="Snake Plant Mini", slug="snake-plant-mini", price=250,
                               stock=10, category=cat, description="Small")
        self.order = Order.objects.create(user=self.user, order_number="ORD123", first_name="Asha", last_name="Rao",
                                          phone="9999999999", email="asha@example.com", address_line_1="a",
                                          address_line_2="b", pin_code="560001", country="IN", state="KA",
                                          city="BLR", order_total=400, tax=0, status="Accepted", is_ordered=True)
        self.client.force_login(self.user)
        # Fresh graph memory per test (the in-memory checkpointer outlives DB rollbacks).
        from agent.langgraph.agent import clear_user_memory
        clear_user_memory(self.user.id)

    def commit(self, fn, *args, **kwargs):
        """Call fn, then run the background tasks it queued once its transaction commits."""
        with self.captureOnCommitCallbacks(execute=True):
            return fn(*args, **kwargs)

    def ask(self, text):
        return self.commit(self.client.post, reverse("ask-agent"), {"message": text}).json()


class EscalationFlowTests(HitlTestBase):
    @mock.patch("agent.langgraph.escalation.extract_intake")
    @mock.patch("agent.langgraph.agent.classify_route")
    def test_price_match_ask_then_staff_edits_discount(self, classify, extract, *_):
        classify.return_value = route("escalation", "price_match")
        extract.side_effect = [
            IntakeExtraction(product_name="Snake Plant", competitor_price="340"),
            IntakeExtraction(product_name="Snake Plant", competitor_price="340", competitor_source="Amazon"),
        ]
        first = self.ask("I found the snake plant for 340 elsewhere, can you match it?")
        self.assertIn("where you found it", first["response"])
        self.assertFalse(EscalationTicket.objects.exists())

        # Second turn goes straight back to intake without re-routing.
        second = self.ask("It was on Amazon")
        self.assertEqual(classify.call_count, 1)
        ticket = EscalationTicket.objects.get()
        self.assertIn(f"#{ticket.pk}", second["response"])
        self.assertEqual(second["ticket"]["id"], ticket.pk)
        self.assertEqual(ticket.mode, "assist")
        self.assertEqual(ticket.status, "awaiting_staff")
        # (400 - 340) / 400 = 15% gap
        self.assertEqual(ticket.proposed_action["type"], "price_match")
        self.assertEqual(ticket.proposed_action["discount_percent"], 15)
        self.assertEqual(ticket.summary, "Customer wants a price match.")

        self.commit(service.resolve_ticket, ticket.pk, {"action": "edit", "params": {"discount_percent": 10}, "note": "Best we can do"},
                               actor=self.staff, source="admin")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "approved")
        self.assertEqual(ticket.assigned_to, self.staff)
        reply = ChatMessage.objects.filter(ticket=ticket, role="agent").latest("id").message
        self.assertIn("REPLY[edit]", reply)
        self.assertIn("10% price match", reply)
        # Approval created a coupon for this customer and product only
        from carts.models import Coupon
        coupon = Coupon.objects.get(ticket=ticket)
        self.assertEqual((coupon.code, coupon.user, coupon.product, coupon.percent, coupon.max_units),
                         ("SNAKEPLANT10", self.user, self.product, 10, 2))
        self.assertAlmostEqual((coupon.expires_at - coupon.created_at).days, 7, delta=1)
        self.assertIn("SNAKEPLANT10", reply)
        self.assertIn("only on this customer's account", reply)
        # The outcome also lands in the user's chat memory (written from inside the escalation graph).
        from agent.langgraph.agent import get_conversation_history
        self.assertEqual(get_conversation_history(self.user.id)[-1].content, reply)
        kinds = list(TicketEvent.objects.filter(ticket=ticket).values_list("kind", flat=True))
        self.assertEqual(kinds[:3], ["created", "posted", "edited"])
        self.assertIn("resolved", kinds)

        # A second click on an already decided ticket is refused.
        with self.assertRaises(ValueError):
            self.commit(service.resolve_ticket, ticket.pk, {"action": "approve"}, actor=self.staff, source="slack")

    @mock.patch("agent.langgraph.escalation.extract_intake", return_value=IntakeExtraction(order_number="ORD123"))
    @mock.patch("agent.langgraph.agent.classify_route", return_value=route("escalation", "cancellation"))
    def test_cancellation_approved_cancels_order(self, *_):
        self.ask("Please cancel order ORD123")
        ticket = EscalationTicket.objects.get()
        self.assertEqual(ticket.proposed_action["type"], "cancel_order")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "Accepted")  # nothing happens before approval

        self.commit(service.resolve_ticket, ticket.pk, {"action": "approve"}, actor=self.staff, source="slack")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "Cancelled")

    @mock.patch("agent.langgraph.escalation.extract_intake", return_value=IntakeExtraction(order_number="ORD123"))
    @mock.patch("agent.langgraph.agent.classify_route", return_value=route("escalation", "cancellation"))
    def test_widget_keeps_polling_until_ai_reply_is_posted(self, *_):
        self.ask("Please cancel order ORD123")
        ticket = EscalationTicket.objects.get()
        # Staff decided, but the worker has not written the AI reply yet.
        queued = []
        with mock.patch("django_q.tasks.async_task", side_effect=lambda *a: queued.append(a)):
            self.commit(service.resolve_ticket, ticket.pk, {"action": "approve"}, actor=self.staff, source="slack")
        gap = self.client.get(reverse("chat_updates")).json()
        self.assertTrue(gap["ticket"]["active"], "widget must keep polling while the reply is pending")
        for args in queued:
            run_now(*args)
        done = self.client.get(reverse("chat_updates")).json()
        self.assertIsNone(done["ticket"])
        self.assertIn("REPLY[approve]", done["messages"][-1]["content"])

    @mock.patch("agent.langgraph.escalation.extract_intake", return_value=IntakeExtraction(order_number="ORD123"))
    @mock.patch("agent.langgraph.agent.classify_route", return_value=route("escalation", "cancellation"))
    def test_rejection_changes_nothing(self, *_):
        self.ask("cancel ORD123")
        ticket = EscalationTicket.objects.get()
        self.commit(service.resolve_ticket, ticket.pk, {"action": "reject", "note": "Already packed"}, actor=self.staff, source="admin")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "Accepted")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "rejected")
        self.assertIn("REPLY[reject]", ChatMessage.objects.filter(ticket=ticket, role="agent").latest("id").message)

    @mock.patch("agent.langgraph.escalation.extract_intake", return_value=IntakeExtraction(order_number="ORD123"))
    @mock.patch("agent.langgraph.agent.classify_route", return_value=route("escalation", "cancellation"))
    def test_staff_can_switch_assist_ticket_to_takeover(self, *_):
        self.ask("cancel ORD123")
        ticket = EscalationTicket.objects.get()
        self.commit(service.start_takeover, ticket.pk, actor=self.staff, source="slack")
        ticket.refresh_from_db()
        self.assertEqual((ticket.mode, ticket.status), ("takeover", "in_takeover"))
        self.assertTrue(ChatMessage.objects.filter(ticket=ticket, role="staff", message__contains="Sam has joined").exists())

    @mock.patch("agent.langgraph.escalation.extract_intake")
    @mock.patch("agent.langgraph.agent.classify_route", return_value=route("escalation", "price_match"))
    def test_user_can_withdraw_during_intake(self, classify, extract, *_):
        extract.side_effect = [IntakeExtraction(product_name="Snake Plant"), IntakeExtraction(user_withdrew=True)]
        self.ask("can you match a price?")
        resp = self.ask("never mind")
        self.assertIn("won't pass this", resp["response"])
        self.assertFalse(EscalationTicket.objects.exists())

    @mock.patch("agent.langgraph.escalation.extract_intake", return_value=IntakeExtraction())
    @mock.patch("agent.langgraph.agent.classify_route", return_value=route("escalation", "price_match"))
    def test_intake_stops_asking_after_two_questions(self, *_):
        self.ask("match price please")
        self.ask("hmm")
        self.assertFalse(EscalationTicket.objects.exists())
        self.ask("I don't know")
        self.assertEqual(EscalationTicket.objects.count(), 1)


class ProposalTests(HitlTestBase):
    def test_find_product_handles_extra_words_and_typos(self):
        from agent.langgraph.escalation import find_product
        self.assertEqual(find_product("snake plant").product_name, "Snake Plant")
        self.assertEqual(find_product("my Snake Plant Mini pot").product_name, "Snake Plant Mini")
        self.assertEqual(find_product("snake plnt").product_name, "Snake Plant")
        self.assertIsNone(find_product("orchid"))

    def test_staff_discount_on_note_only_ticket_is_a_price_match(self):
        from agent.hitl.actions import apply_action
        ticket = self.commit(service.create_ticket, user_id=self.user.id, category="price_match",
                             collected={"product_name": "Snake Plant"}, trigger="test", mode="assist")
        ticket.refresh_from_db()
        ticket.proposed_action = {"type": "note_only"}
        out = apply_action(ticket, {"action": "edit", "params": {"discount_percent": 10}})
        self.assertIn("10% price match on Snake Plant", out)


class TakeoverTests(HitlTestBase):
    def test_keyword_hands_over_and_ai_goes_quiet(self, *_):
        with mock.patch("agent.langgraph.agent.classify_route") as classify:
            resp = self.ask("I want to talk to a human please")
            classify.assert_not_called()  # hard trigger, no LLM routing
        ticket = EscalationTicket.objects.get()
        self.assertEqual((ticket.category, ticket.mode, ticket.status), ("human_request", "takeover", "in_takeover"))
        self.assertEqual(resp["ticket"]["mode"], "takeover")

        with mock.patch("agent.views.run_supervisor_agent") as agent:
            relayed = self.ask("My order never arrived")
            agent.assert_not_called()
        self.assertTrue(relayed["handoff"])
        self.assertTrue(ChatMessage.objects.filter(ticket=ticket, role="user", message="My order never arrived").exists())

        last_seen = relayed["message_id"]
        self.commit(service.post_staff_message, ticket, "Hi Asha, checking with the courier now.", actor=self.staff, source="admin")
        updates = self.client.get(reverse("chat_updates"), {"after_id": last_seen}).json()
        self.assertEqual([m["role"] for m in updates["messages"]], ["staff"])
        self.assertEqual(updates["messages"][0]["author"], "Sam")
        self.assertEqual(updates["ticket"]["status"], "in_takeover")

        self.commit(service.end_takeover, ticket.pk, actor=self.staff, source="admin")
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.staff)  # recorded even without a decision
        updates = self.client.get(reverse("chat_updates"), {"after_id": last_seen}).json()
        self.assertIsNone(updates["ticket"])
        self.assertIn("back with the Plantae assistant", updates["messages"][-1]["content"])

        # Staff messages were added to the AI's memory for later turns.
        from agent.langgraph.agent import get_conversation_history
        history = [m.content for m in get_conversation_history(self.user.id)]
        self.assertTrue(any("[Plantae team]: Hi Asha" in h for h in history))

    def test_worker_running_late_does_not_reopen_resolved_ticket(self, *_):
        queued = []
        with mock.patch("django_q.tasks.async_task", side_effect=lambda *a: queued.append(a)):
            ticket = self.commit(service.create_ticket, user_id=self.user.id, category="human_request",
                                 collected={}, trigger="test", mode="takeover")
            self.commit(service.end_takeover, ticket.pk, actor=self.staff, source="admin")
        for args in queued:  # the worker finally gets to the queued jobs
            run_now(*args)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "resolved")
        self.assertEqual(ticket.summary, "Customer wants a price match.")  # summary still filled in

    def test_talk_to_human_button(self, *_):
        resp = self.commit(self.client.post, reverse("request_human")).json()
        self.assertEqual(resp["ticket"]["mode"], "takeover")
        again = self.commit(self.client.post, reverse("request_human")).json()
        self.assertEqual(again["ticket"]["id"], resp["ticket"]["id"])
        self.assertEqual(EscalationTicket.objects.count(), 1)

    def test_repeated_errors_trigger(self, *_):
        from agent.error_logging import USER_FACING_ERROR
        for _ in range(2):
            ChatMessage.objects.create(user=self.user, role="user", message="hello")
            ChatMessage.objects.create(user=self.user, role="agent", message=USER_FACING_ERROR)
        self.assertEqual(detect_hard_triggers(self.user.id, "anything")["trigger"], "repeated_errors")

    def test_hard_trigger_does_not_fire_on_normal_text(self, *_):
        for text in ["what's in my cart", "how do I care for a human-sized monstera", "show my orders"]:
            self.assertIsNone(detect_hard_triggers(self.user.id, text), text)

    def test_message_limit_does_not_block_user_with_open_ticket(self, *_):
        from django.core.cache import cache
        self.commit(service.create_ticket, user_id=self.user.id, category="price_match", collected={}, trigger="test", mode="assist")
        cache.set(f"chat_limit_user_{self.user.id}", 10, None)
        try:
            with mock.patch("agent.views.run_supervisor_agent") as agent:
                resp = self.ask("any update?")
                agent.assert_not_called()
            self.assertIn("is with our team", resp["response"])
        finally:
            cache.delete(f"chat_limit_user_{self.user.id}")


class MemoryTests(HitlTestBase):
    @mock.patch("agent.langgraph.agent.research_agent")
    @mock.patch("agent.langgraph.agent.classify_route", return_value=route("research"))
    def test_only_new_message_sent_once_memory_exists(self, classify, research, *_):
        from langchain_core.messages import AIMessage
        research.invoke.return_value = {"messages": [AIMessage(content="Water weekly.")]}
        ChatMessage.objects.create(user=self.user, role="user", message="old question")
        ChatMessage.objects.create(user=self.user, role="agent", message="old answer")
        self.ask("How often to water a snake plant?")
        self.ask("And in winter?")
        from agent.langgraph.agent import get_conversation_history
        contents = [m.content for m in get_conversation_history(self.user.id)]
        # Seeded once from DB, then only new turns; replies are kept in memory.
        self.assertEqual(contents, ["old question", "old answer", "How often to water a snake plant?",
                                    "Water weekly.", "And in winter?", "Water weekly."])


class RoutingTests(HitlTestBase):
    @mock.patch("agent.langgraph.agent.general_reply", return_value="They're sending a replacement today.")
    @mock.patch("agent.langgraph.agent.classify_route")
    def test_follow_up_after_handback_goes_to_general_not_new_ticket(self, classify, general, *_):
        ticket = self.commit(service.create_ticket, user_id=self.user.id, category="human_request", collected={},
                             trigger="test", mode="takeover")
        self.commit(service.post_staff_message, ticket, "Sending a replacement today.", actor=self.staff, source="admin")
        self.commit(service.end_takeover, ticket.pk, actor=self.staff, source="admin")
        classify.return_value = route("general")
        resp = self.ask("Thanks! What did the team say they'd do?")
        self.assertEqual(resp["response"], "They're sending a replacement today.")
        self.assertEqual(EscalationTicket.objects.count(), 1)
        # Supervisor got the recent conversation as context.
        self.assertIn("Recent conversation", classify.call_args[0][0])

    @mock.patch("agent.langgraph.agent.general_reply", return_value="Happy to help!")
    @mock.patch("agent.langgraph.agent.classify_route",
                return_value=RouteDecision(route="escalation", escalation_category="other", confidence=0.4))
    def test_low_confidence_other_escalation_falls_back_to_general(self, *_):
        resp = self.ask("hmm ok")
        self.assertEqual(resp["response"], "Happy to help!")
        self.assertFalse(EscalationTicket.objects.exists())


class RealScenarioFixTests(HitlTestBase):
    def test_quantity_from_text(self):
        from agent.langgraph.agent import quantity_from_text
        self.assertEqual(quantity_from_text("pls ad 2 marigolds in my crt"), 2)  # common typo
        self.assertEqual(quantity_from_text("add 2 marigolds"), 2)
        self.assertEqual(quantity_from_text("I want three roses"), 3)
        self.assertEqual(quantity_from_text("put 3x jade in cart"), 3)
        self.assertEqual(quantity_from_text("add rose to my cart"), 1)
        self.assertEqual(quantity_from_text("what about order 123"), 1)

    def test_cart_tools_match_names_with_extra_words(self):
        from agent.langgraph.tools import add_to_cart, resolve_product
        cat = Category.objects.get(category_name="Plants")
        Product.objects.create(product_name="Jade", slug="jade", price=100, stock=5, category=cat, description="x")
        self.assertEqual(resolve_product("jade plant")[0].product_name, "Jade")
        out = add_to_cart.invoke({"user_id": self.user.id, "product_name": "jade plant", "quantity": 2})
        self.assertIn("2 × Jade", out)
        self.assertEqual(CartItem.objects.get(product__product_name="Jade").quantity, 2)
        add_to_cart.invoke({"user_id": self.user.id, "product_name": "Jade", "quantity": 3})
        self.assertEqual(CartItem.objects.get(product__product_name="Jade").quantity, 5)

    @mock.patch("agent.langgraph.escalation.extract_intake", return_value=IntakeExtraction(order_number="ORD123"))
    @mock.patch("agent.langgraph.agent.classify_route",
                return_value=RouteDecision(route="escalation", escalation_category="payment_issue", sentiment="angry"))
    def test_angry_customer_goes_straight_to_a_person(self, *_):
        resp = self.ask("THIRD time asking, where is my refund?? useless")
        ticket = EscalationTicket.objects.get()
        self.assertEqual((ticket.mode, ticket.status, ticket.trigger), ("takeover", "in_takeover", "angry_sentiment"))
        self.assertIn("really sorry", resp["response"])

    def test_store_links_use_site_url(self):
        from agent.langgraph.tools import get_checkout_url
        with self.settings(SITE_URL="http://localhost:8000"):
            self.assertIn("http://localhost:8000/cart/checkout/", get_checkout_url.invoke({"user_id": self.user.id}))


class ToolFixTests(HitlTestBase):
    def test_add_to_cart_ambiguous_adds_nothing(self, *_):
        from agent.langgraph.tools import add_to_cart
        Product.objects.filter(product_name="Snake Plant").update(product_name="Snake Plant Large", slug="spl")
        out = add_to_cart.invoke({"user_id": self.user.id, "product_name": "Snake"})
        self.assertIn("Nothing was added", out)
        self.assertFalse(CartItem.objects.exists())

    def test_remove_prefers_exact_and_refuses_ambiguous(self, *_):
        from agent.langgraph.tools import remove_cart_item
        mini = Product.objects.get(product_name="Snake Plant Mini")
        CartItem.objects.create(user=self.user, product=self.product, quantity=1)
        CartItem.objects.create(user=self.user, product=mini, quantity=1)
        self.assertIn("Nothing was removed", remove_cart_item.invoke({"user_id": self.user.id, "product_name": "snake"}))
        self.assertEqual(CartItem.objects.count(), 2)
        self.assertIn("Removed Snake Plant from", remove_cart_item.invoke({"user_id": self.user.id, "product_name": "Snake Plant"}))
        self.assertEqual(list(CartItem.objects.values_list("product__product_name", flat=True)), ["Snake Plant Mini"])


@override_settings(SLACK_SIGNING_SECRET="test-secret", SLACK_BOT_TOKEN="", SLACK_ESCALATION_CHANNEL="")
class SlackWebhookTests(HitlTestBase):
    def signed_post(self, url, body, content_type):
        ts = str(int(time.time()))
        sig = "v0=" + hmac.new(b"test-secret", f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
        return self.commit(self.client.generic, "POST", url, body, content_type=content_type,
                           HTTP_X_SLACK_REQUEST_TIMESTAMP=ts, HTTP_X_SLACK_SIGNATURE=sig)

    def test_unsigned_request_rejected(self, *_):
        resp = self.client.post(reverse("slack_interactions"), {"payload": "{}"})
        self.assertEqual(resp.status_code, 403)

    @mock.patch("agent.hitl.slack.staff_account")
    @mock.patch("agent.langgraph.escalation.extract_intake", return_value=IntakeExtraction(order_number="ORD123"))
    @mock.patch("agent.langgraph.agent.classify_route", return_value=route("escalation", "cancellation"))
    def test_approve_button(self, classify, extract, staff_account, *_):
        staff_account.return_value = self.staff
        self.ask("cancel ORD123")
        ticket = EscalationTicket.objects.get()
        payload = {"type": "block_actions", "user": {"id": "U1", "username": "sam"},
                   "actions": [{"action_id": "hitl_approve", "value": str(ticket.pk)}]}
        resp = self.signed_post(reverse("slack_interactions"), urlencode({"payload": json.dumps(payload)}),
                                "application/x-www-form-urlencoded")
        self.assertEqual(resp.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "approved")
        self.assertEqual(ticket.final_action["slack_user"], "sam")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "Cancelled")

    @mock.patch("agent.hitl.slack.staff_account", return_value=None)
    def test_thread_reply_reaches_user_only_in_takeover(self, *_):
        ticket = self.commit(service.create_ticket, user_id=self.user.id, category="human_request", collected={},
                                       trigger="test", mode="takeover")
        EscalationTicket.objects.filter(pk=ticket.pk).update(slack_ts="111.222", slack_channel="C1")
        body = json.dumps({"type": "event_callback", "event": {
            "type": "message", "channel": "C1", "thread_ts": "111.222", "ts": "111.333", "user": "U1",
            "text": "Hello from Slack"}})
        self.assertEqual(self.signed_post(reverse("slack_events"), body, "application/json").status_code, 200)
        self.assertTrue(ChatMessage.objects.filter(ticket=ticket, role="staff", message="Hello from Slack").exists())

    @mock.patch("agent.hitl.slack.post_thread")
    @mock.patch("agent.hitl.slack.post_ticket", return_value=("999.000", "C1"))
    def test_messages_sent_before_card_reach_thread_exactly_once(self, post_ticket, post_thread):
        from agent.hitl.tasks import relay_message_to_slack
        with self.settings(SLACK_BOT_TOKEN="xoxb-test", SLACK_ESCALATION_CHANNEL="C1"):
            queued = []
            with mock.patch("django_q.tasks.async_task", side_effect=lambda *a: queued.append(a)):
                ticket = self.commit(service.create_ticket, user_id=self.user.id, category="human_request",
                                     collected={}, trigger="test", mode="takeover")
                msg = self.commit(service.relay_user_message, ticket, "typed before the card existed")
            relay = [a for a in queued if a[0].endswith("relay_message_to_slack")]
            run_now(*relay[0])                     # relay runs first: no card yet, nothing posted
            self.assertFalse(post_thread.called)
            run_now(*[a for a in queued if a[0].endswith("run_escalation")][0])  # card posted, catches up
            relay_message_to_slack(ticket.pk, msg.pk)  # a late duplicate attempt is ignored
        self.assertEqual(post_thread.call_count, 1)
        self.assertIn("typed before the card existed", post_thread.call_args[0][1])

    def test_url_verification(self, *_):
        resp = self.signed_post(reverse("slack_events"), json.dumps({"type": "url_verification", "challenge": "abc"}),
                                "application/json")
        self.assertEqual(resp.json(), {"challenge": "abc"})


class AdminDecisionTests(HitlTestBase):
    @mock.patch("agent.langgraph.escalation.extract_intake", return_value=IntakeExtraction(order_number="ORD123"))
    @mock.patch("agent.langgraph.agent.classify_route", return_value=route("escalation", "cancellation"))
    def test_admin_form_approves(self, *_):
        self.ask("cancel ORD123")
        ticket = EscalationTicket.objects.get()
        self.staff.is_admin = self.staff.is_superadmin = True
        self.staff.save()
        self.client.force_login(self.staff)
        url = reverse("admin:agent_escalationticket_change", args=[ticket.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        resp = self.commit(self.client.post, url, {"assigned_to": self.staff.pk, "decision": "approve", "note": "",
                                      "reply_to_user": "", "events-TOTAL_FORMS": 0, "events-INITIAL_FORMS": 0})
        self.assertEqual(resp.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "approved")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "Cancelled")
