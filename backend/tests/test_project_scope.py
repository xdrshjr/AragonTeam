"""项目作用域过滤（scale-and-project-scope §2.4）+ 看板 position 项目隔离（§2.5）。

覆盖点（对应 spec §3.2）：
① `?project_id=<id>` 只返该项目；② `?project_id=none` 只返 IS NULL；
③ `?project_id=abc` → 400 且 detail.field == "project_id"（需求 / BUG / board / stats 各断一次）；
④ 向后兼容：缺省时结果集与改造前一致；⑤ 看板列结构不变；
⑥ `project_id=99999` → 200 空结果（不 404）；⑦ §2.5 回归：项目内看板按索引 move 后次序确实改变。
"""
from models.project import Project
from extensions import db


def _new_project(app, key="P2", name="第二项目"):
    with app.app_context():
        p = Project(name=name, key=key)
        db.session.add(p)
        db.session.commit()
        return p.id


def _create(client, headers, title, project_id=None):
    body = {"title": title}
    if project_id is not None:
        body["project_id"] = project_id
    r = client.post("/api/requirements", json=body, headers=headers)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


# ————————————————————— ① / ② / ⑥ 过滤语义 —————————————————————

def test_filters_requirements_by_project(client, auth, data, app):
    headers = auth("pm")
    other = _new_project(app)
    a = _create(client, headers, "属于 TST", data["project_id"])
    b = _create(client, headers, "属于 P2", other)
    c = _create(client, headers, "未归属")

    r = client.get(f"/api/requirements?project_id={data['project_id']}", headers=headers)
    assert r.status_code == 200
    assert [x["id"] for x in r.get_json()] == [a["id"]]

    r = client.get(f"/api/requirements?project_id={other}", headers=headers)
    assert [x["id"] for x in r.get_json()] == [b["id"]]

    # ② 字面量 none = 仅未归属（project_id IS NULL）。
    r = client.get("/api/requirements?project_id=none", headers=headers)
    ids = [x["id"] for x in r.get_json()]
    assert c["id"] in ids
    assert a["id"] not in ids and b["id"] not in ids


def test_unknown_project_id_returns_empty_not_404(client, auth):
    """⑥ 不存在的项目 id 是合法查询，返 200 空集——不是 404。"""
    r = client.get("/api/requirements?project_id=99999", headers=auth("pm"))
    assert r.status_code == 200
    assert r.get_json() == []


def test_filters_bugs_by_project(client, auth, data, app):
    headers = auth("pm")
    other = _new_project(app, key="P3", name="第三项目")
    r = client.post("/api/bugs", json={"title": "TST 的 BUG",
                                       "project_id": data["project_id"]}, headers=headers)
    scoped = r.get_json()
    client.post("/api/bugs", json={"title": "P3 的 BUG", "project_id": other}, headers=headers)
    client.post("/api/bugs", json={"title": "未归属 BUG"}, headers=headers)

    r = client.get(f"/api/bugs?project_id={data['project_id']}", headers=headers)
    assert [x["id"] for x in r.get_json()] == [scoped["id"]]

    r = client.get("/api/bugs?project_id=none", headers=headers)
    titles = [x["title"] for x in r.get_json()]
    assert titles == ["未归属 BUG"]


def test_board_filters_by_project(client, auth, data, app):
    headers = auth("pm")
    other = _new_project(app, key="P4", name="第四项目")
    _create(client, headers, "TST 需求", data["project_id"])
    _create(client, headers, "P4 需求", other)

    r = client.get(f"/api/board/requirements?project_id={other}", headers=headers)
    assert r.status_code == 200
    items = [i for col in r.get_json()["columns"] for i in col["items"]]
    assert [i["title"] for i in items] == ["P4 需求"]


# ————————————————————— ③ 非法值 → 400 —————————————————————

def test_invalid_project_id_returns_400_everywhere(client, auth):
    headers = auth("pm")
    for path in ("/api/requirements", "/api/bugs",
                 "/api/board/requirements", "/api/board/bugs", "/api/stats"):
        r = client.get(f"{path}?project_id=abc", headers=headers)
        assert r.status_code == 400, (path, r.status_code, r.get_json())
        body = r.get_json()
        assert body["error"] == "invalid project_id"
        assert body["detail"]["field"] == "project_id"


# ————————————————————— ④ / ⑤ 向后兼容 —————————————————————

def test_no_project_id_returns_everything(client, auth, data, app):
    """④ 不带 project_id 时结果集与改造前一致（含已归属与未归属）。"""
    headers = auth("pm")
    other = _new_project(app, key="P5", name="第五项目")
    a = _create(client, headers, "A", data["project_id"])
    b = _create(client, headers, "B", other)
    c = _create(client, headers, "C")

    r = client.get("/api/requirements", headers=headers)
    ids = {x["id"] for x in r.get_json()}
    assert {a["id"], b["id"], c["id"]} <= ids


def test_board_column_structure_unchanged(client, auth):
    """⑤ 列数与列 key 顺序不因项目过滤而改变。"""
    headers = auth("pm")
    full = client.get("/api/board/requirements", headers=headers).get_json()
    scoped = client.get("/api/board/requirements?project_id=none", headers=headers).get_json()
    assert [c["key"] for c in full["columns"]] == [c["key"] for c in scoped["columns"]]
    assert len(full["columns"]) == 7


# ————————————————————— ⑦ §2.5 position 项目隔离回归 —————————————————————

def test_move_within_project_board_actually_reorders(client, auth, data, app):
    """项目 A 的卡不得污染项目 B 看板的插入索引（§2.5 实机复现的缺陷）。"""
    headers = auth("pm")
    pa = data["project_id"]
    pb = _new_project(app, key="P6", name="第六项目")
    a1 = _create(client, headers, "A1", pa)
    a2 = _create(client, headers, "A2", pa)
    b1 = _create(client, headers, "B1", pb)
    b2 = _create(client, headers, "B2", pb)
    b3 = _create(client, headers, "B3", pb)

    def board_ids(project_id):
        r = client.get(f"/api/board/requirements?project_id={project_id}", headers=headers)
        col = next(c for c in r.get_json()["columns"] if c["key"] == "new")
        return [i["id"] for i in col["items"]]

    assert board_ids(pb) == [b1["id"], b2["id"], b3["id"]]
    before_a = board_ids(pa)

    # 在项目 B 的看板里把 B1 拖到末位（索引 2）。
    r = client.patch(f"/api/requirements/{b1['id']}/move",
                     json={"status": "new", "position": 2}, headers=headers)
    assert r.status_code == 200, r.get_json()

    assert board_ids(pb) == [b2["id"], b3["id"], b1["id"]]
    # 项目 A 的次序完全不受影响。
    assert board_ids(pa) == before_a
    assert before_a == [a1["id"], a2["id"]]


def test_next_position_is_per_project(client, auth, data, app):
    """新建单的 position 在**同项目同状态**列内从 0 开始，不与别的项目连号。"""
    headers = auth("pm")
    pb = _new_project(app, key="P7", name="第七项目")
    _create(client, headers, "A1", data["project_id"])
    _create(client, headers, "A2", data["project_id"])
    first_b = _create(client, headers, "B1", pb)
    assert first_b["position"] == 0
