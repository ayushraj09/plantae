def user_context(request):
    """
    Context processor to make user information available globally
    """
    if request.user.is_authenticated:
        return {
            'user_full_name': request.user.full_name(),
            'user_first_name': request.user.first_name,
            'user_last_name': request.user.last_name,
        }
    return {
        'user_full_name': None,
        'user_first_name': None,
        'user_last_name': None,
    }