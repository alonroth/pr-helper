
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from github import Github, Auth

from app.comment_suggest import comment_suggest
from app.config import GITHUB_APP_PRIVATE_KEY, GITHUB_APP_ID, GITHUB_APP_SECRET
from app.pr_summarize import pr_summarize, SUMMARY_MAGIC_PHRASE
from app.utils import github_verify_signature

app = FastAPI()


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    x_hub_signature = request.headers.get('X-Hub-Signature')
    payload = await request.json()
    body = await request.body()

    if not github_verify_signature(GITHUB_APP_SECRET, x_hub_signature, body):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        action = payload['action']
        repo_name = payload['repository']['full_name']
        pr_number = payload['pull_request']['number']
        installation_id = payload['installation']['id']
    except KeyError:
        raise HTTPException(status_code=400, detail="Invalid payload - missing action, "
                                                    "repo name, PR number, "
                                                    "or installation ID")

    auth = Auth.AppAuth(GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY).get_installation_auth(installation_id)
    g = Github(auth=auth)
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(pr_number)

    if 'pull_request' in payload and action in ('opened', 'edited') \
            and SUMMARY_MAGIC_PHRASE in pr.body:
        return pr_summarize(repo, pr, background_tasks)
    if 'comment' in payload and action in ('created', 'edited'):
        return comment_suggest(pr, payload, background_tasks)

    return {"message": "Webhook received, but no action taken."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
