from api.services import project_store


def test_project_upsert_preserves_history_and_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFEOS_PROJECTS_PATH", str(tmp_path / "projects.json"))
    first = project_store.upsert(
        "Cafe AI",
        status="potential",
        summary="A management product for cafes",
        source={"type": "telegram", "message_id": "1"},
    )
    second = project_store.upsert(
        " cafe   ai ",
        status="active",
        next_action="Map the first workflow",
        source={"type": "telegram", "message_id": "2"},
    )

    assert first["id"] == second["id"]
    current = project_store.get_project(name="Cafe AI")
    assert current["status"] == "active"
    assert current["next_action"] == "Map the first workflow"
    assert len(current["history"]) == 1
    assert len(current["sources"]) == 2


def test_project_list_hides_archived_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFEOS_PROJECTS_PATH", str(tmp_path / "projects.json"))
    item = project_store.upsert("Old project", status="active")
    project_store.upsert("Old project", status="archived")
    assert project_store.list_projects() == []
    assert project_store.list_projects(include_archived=True)[0]["id"] == item["id"]


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFEOS_PROJECTS_PATH", str(tmp_path / "projects.json"))


class TestProjectIdentity:
    """One project, however it gets named next time.

    A live deployment carried "Café AI product" and "Cafe AI" as two separate
    projects, because upsert matched the name as an exact string. The second
    record then took all the new information while the first kept a stale
    summary — which is how the assistant ended up describing a project's state
    from a record nobody had updated in two weeks.
    """

    def test_an_accent_does_not_create_a_second_project(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        first = project_store.upsert("Café AI product", summary="Build an AI product for cafés.")
        second = project_store.upsert("Cafe AI", status="active", summary="Partnership with Qaf.")

        assert second["id"] == first["id"]
        assert len(project_store.list_projects()) == 1

    def test_the_update_lands_on_the_existing_project(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        project_store.upsert("Café AI product", status="potential", summary="Just an idea.")
        project_store.upsert("Cafe AI", status="active", summary="Owner of Qaf agreed.")

        [project] = project_store.list_projects()
        assert project["status"] == "active"
        assert project["summary"] == "Owner of Qaf agreed."
        assert project["history"], "the previous state is kept"

    def test_the_original_name_is_kept(self, tmp_path, monkeypatch):
        """Renaming is a separate act from updating; a restatement of the same
        subject must not silently rewrite what the project is called."""
        _isolate(tmp_path, monkeypatch)
        project_store.upsert("Café AI product")
        project_store.upsert("cafe ai PRODUCT", summary="More detail.")

        [project] = project_store.list_projects()
        assert project["name"] == "Café AI product"

    def test_word_order_and_filler_do_not_fork_a_project(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        first = project_store.upsert("Clock Chrome extension")
        second = project_store.upsert("the Chrome clock extension project")

        assert second["id"] == first["id"]

    def test_genuinely_different_projects_stay_separate(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        project_store.upsert("GeoQ")
        project_store.upsert("Halal Protocol")
        project_store.upsert("Car repair")

        assert len(project_store.list_projects()) == 3

    def test_lookup_finds_a_project_under_a_different_spelling(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        created = project_store.upsert("Café AI product")

        assert project_store.get_project(name="cafe ai")["id"] == created["id"]
