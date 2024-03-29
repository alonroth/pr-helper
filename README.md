<p align="center">
  <img src="./logo.png" alt="PR Helper Logo" width="200" height="200">
</p>

# PR Helper

PR Helper will write concise summaries of your pull requests and intelligent suggestions within your PR discussions.

## Features

- **PR Summarization:** Write `ai:summary` in your PR body to generate a summary for pull requests.
- **Comment Suggestions:** Write `ai:suggest` together inside code review comment together with a request, and it will generate and post relevant suggestion.

## Setup Guide

### Step 1: Create a New GitHub App

1. Navigate to your GitHub account settings.
2. Go to "Developer settings" > "GitHub Apps" > "New GitHub App".
3. Fill in the necessary details:
   - **GitHub App name:** Give your app a name.
   - **Webhook URL:** Your deployment's URL (you'll update this after deploying your app, e.g., `https://yourapp.example.com/webhook`).
   - **Webhook Secret:** Generate a secret and note it down; you'll use this in your `.env` file.
   
4. **Select the following permissions:**
   - **Contents:** Read and Write
   - **Issues:** Read and Write
   - **Metadata:** Read only
   - **Pull requests:** Read and Write

5. **Select the following Subscribe to events:**
   - **Pull request**
   - **Pull request review comment**

6. Click "Create GitHub App".

### Step 2: Deploy Your Application

Deploy your application to your preferred hosting service (e.g., Heroku, AWS). Ensure it's accessible via a public URL.

### Step 3: Update Your GitHub App Settings

After deployment, update your GitHub App's **Webhook URL** with your deployed application's URL.

### Step 4: Setting Up Environment Variables

Copy the `.env.example` file to `.env` in the root of your project to store your environment variables. Here's an example `.env` file:

```env
GITHUB_APP_ID=your_app_id
GITHUB_APP_WEBHOOK_SECRET=your_webhook_secret
GITHUB_APP_PRIVATE_KEY=your_base64_encoded_private_key

OPENAI_API_KEY=your_openai_key
```

## Limitations
- Currently, we are processing every file that is changed in the PR in a dedicated OpenAI call simulataneously. This can be improved by batching the files and processing them by the max token limit.
- The current implementation is not optimized for large PRs with multiple changes as it can reach the OpenAI max token limit. This can be improved by summarizing the PR in chunks and then combining the results.