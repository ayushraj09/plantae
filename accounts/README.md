# Accounts App

## Purpose
Handles user authentication, registration, profile management, and user dashboard for the Plantae project.

## Main Features
- Custom user model (`Account`) with email as the username.
- User registration, login, logout, and email activation via email.
- User profile management (`UserProfile`), including address, pin code, city, state, country, and profile picture.
- Password reset and change.
- User dashboard showing order count and profile info.
- Context processor for user info in templates.

## Key Models
- **Account**: Custom user model (extends `AbstractBaseUser`).
- **UserProfile**: One-to-one with `Account`, stores address, pin code, city, state, country, and profile picture.

## Key Views
- `register`, `login`, `logout`, `activate`: User authentication and activation.
- `dashboard`: User dashboard with order info.
- `edit_profile`: Edit user profile.
- Password reset and change views.

## Forms
- `RegistrationForm`: Handles user registration and validation.
- `UserForm`, `UserProfileForm`: For editing user and profile info.

## Context Processors
- `user_context`: Makes user info available globally in templates.

## Admin
- Admin actions to reset chat limits for users.

## Templates
- Registration, login, dashboard, profile edit, password reset, and order detail templates.

## Signals & Utilities
- Automatic creation of `UserProfile` on registration.
- Email activation and password reset via Django's token system.

## Notes
- Integrates with other apps for cart and order info.
- Designed for extensibility and security. 