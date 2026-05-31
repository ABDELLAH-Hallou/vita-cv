from vita.commands import sync
from vita.helpers import git

DEFAULT_MESSAGE = "chore: save CV changes"
MASTER_BRANCH = "master"

def run(message: str | None = None, reconcile: bool = False) -> None:
    message = message or DEFAULT_MESSAGE
    result = git.add_commit_push(message=message)

    if not reconcile:
        return result

    checkout = git.checkout(MASTER_BRANCH)
    if not checkout.ok:
        print(checkout.stderr or checkout.stdout)
        return checkout

    sync.run(auto=True)
    return git.add_commit_push(message=message)
