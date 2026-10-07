from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create/upgrade the LangGraph checkpoint tables used for agent memory and escalations."

    def handle(self, *args, **options):
        from agent.langgraph.checkpointer import checkpointer
        if not hasattr(checkpointer, "setup"):
            self.stdout.write("In-memory checkpointer configured; nothing to set up.")
            return
        checkpointer.setup()
        self.stdout.write(self.style.SUCCESS("LangGraph checkpoint tables are ready."))
