"""vita lock / unlock — toggle the lock flag on a company in the registry."""

from vita.utils import load_registry, save_registry, log


def run(company: str, locked: bool = True) -> None:
    company  = company.lower()
    registry = load_registry()

    if company not in registry:
        print(f"❌ Company '{company}' not found in registry.")
        print("   Use `vita status` to see all registered companies.")
        return

    registry[company]["locked"] = locked
    save_registry(registry)

    action = "locked" if locked else "unlocked"
    icon   = "🔒" if locked else "🔓"

    log(f"{action.capitalize()} company: '{company}'")
    print(f"{icon} Company '{company}' is now {action}.")

    if locked:
        print("   New CV branches for this company will be blocked.")
    else:
        print("   New CV branches for this company are allowed again.")
