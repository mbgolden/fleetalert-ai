from fleetalert.repositories import get_alert, get_machine, search_knowledge_base
from fleetalert.seed_data import SEED_ALERTS, SEED_MACHINES
from scripts.seed_demo_data import main


def test_seed_demo_data_loads_everything(dynamodb_tables: None) -> None:
    main()

    for machine in SEED_MACHINES:
        assert get_machine(machine["machine_id"]) is not None
    for alert in SEED_ALERTS:
        assert get_alert(alert["alert_id"]) is not None

    assert len(search_knowledge_base("diesel_engine", "coolant temp spike")) == 2


def test_seed_demo_data_is_safe_to_rerun(dynamodb_tables: None) -> None:
    main()
    main()  # should overwrite, not raise

    assert get_alert("ALERT-1001") is not None
