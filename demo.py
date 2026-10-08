"""Run an unprivileged, reproducible governance walkthrough."""

from governance import Controller, InMemoryNotes, Proposal


def main() -> None:
    store = InMemoryNotes()
    controller = Controller(store)

    print("1. Unapproved write")
    write = Proposal("demo-1", "notes.write", {"key": "lesson", "value": "Verify effects"})
    pending = controller.propose(write)
    print(pending.status, pending.reason, "writes:", store.write_count)
    assert pending.status == "WAITING_CONFIRMATION"
    assert pending.confirmation_id is not None
    assert store.write_count == 0

    print("2. Explicit human approval through the demo host")
    result = controller.confirm(pending.confirmation_id, approved=True)
    print(result.status, result.reason, "writes:", store.write_count)
    assert result.verified

    print("3. Idempotent retry")
    retry = controller.propose(write)
    print(retry.status, "writes:", store.write_count)
    assert retry == result
    assert store.write_count == 1

    print("4. A forged new capability is refused")
    denied = controller.propose(Proposal("demo-2", "os.shell", {"command": "echo hi"}))
    print(denied.status, denied.reason)
    assert denied.status == "DENIED"


if __name__ == "__main__":
    main()