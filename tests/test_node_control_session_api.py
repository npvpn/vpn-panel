from app.models.node import NodeResponse


def test_node_response_has_no_control_session_field():
    assert "control_session_id" not in NodeResponse.model_fields
