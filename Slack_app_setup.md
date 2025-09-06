# Slack App Setup Guide

## 1. Create Slack App
1. Go to https://api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. Name your app (e.g., "TERminus")
4. Select your workspace

## 2. Configure OAuth & Permissions
Navigate to "OAuth & Permissions" and add these Bot Token Scopes:
- `app_mentions:read` - Read mentions
- `channels:history` - Read channel messages
- `channels:read` - List channels
- `chat:write` - Send messages
- `im:history` - Read direct messages
- `im:read` - List direct messages
- `im:write` - Send direct messages
- `users:read` - Get user info

## 3. Enable Event Subscriptions
1. Go to "Event Subscriptions"
2. Enable Events
3. Add Bot User Events:
   - `app_mention` - When bot is mentioned
   - `message.channels` - Channel messages
   - `message.im` - Direct messages

## 4. Install App
1. Go to "Install App"
2. Click "Install to Workspace"
3. Copy the Bot User OAuth Token (starts with xoxb-)

## 5. Set Environment Variables
Add to your .env file:
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_APP_TOKEN=xapp-your-app-token  # For socket mode
SLACK_SIGNING_SECRET=your-signing-secret

## 6. Enable Socket Mode (Recommended)
1. Go to "Socket Mode"
2. Enable Socket Mode
3. Generate an App-Level Token with `connections:write` scope
4. Use this token as SLACK_APP_TOKEN

