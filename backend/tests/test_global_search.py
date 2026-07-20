"""全局统一搜索端点回归（global-search §7.1）。GET /api/search。

覆盖：双实体命中、描述命中、空 q 降级、limit 上/下限、鉴权 401、
LIKE 元字符转义（R2 真回归护栏）、无命中空组。
复用 conftest fixture（client/auth/make_requirement/make_bug）；需指定
description 或用作转义诱饵的用例直建（make_* 无 description 形参，见 §7.1 注）。
"""


def _post_req(client, auth, title, description=None):
    """以 pm 直建需求（可带 description），返回响应 dict。"""
    payload = {"title": title}
    if description is not None:
        payload["description"] = description
    r = client.post("/api/requirements", json=payload, headers=auth("pm"))
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def test_search_returns_both_entities(client, auth, make_requirement, make_bug):
    make_requirement(title="登录页面")
    make_bug(title="登录失败")
    r = client.get("/api/search?q=登录", headers=auth("member"))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["query"] == "登录"
    assert [x["title"] for x in body["requirements"]] == ["登录页面"]
    assert [x["title"] for x in body["bugs"]] == ["登录失败"]
    # 【document-lifecycle-depth §4.7】信封新增第三个桶 documents，counts 同步扩为三键。
    assert body["counts"] == {"requirements": 1, "bugs": 1, "documents": 0}


def test_search_matches_description(client, auth):
    _post_req(client, auth, title="用户中心", description="包含改密流程")
    r = client.get("/api/search?q=改密", headers=auth("member"))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert [x["title"] for x in body["requirements"]] == ["用户中心"]
    assert body["counts"]["requirements"] == 1


def test_search_blank_query_returns_empty(client, auth):
    r = client.get("/api/search", headers=auth("member"))
    assert r.status_code == 200
    body = r.get_json()
    # 空信封必须与 `search_all` **同形状**：前端直接解构 counts.documents 并 .map
    # 结果数组，少一个键就是清空搜索框时的一次运行时崩溃（§2.1 A-1）。
    assert body == {
        "query": "", "requirements": [], "bugs": [], "documents": [],
        "counts": {"requirements": 0, "bugs": 0, "documents": 0},
    }


def test_search_limit_caps_preview_but_counts_total(client, auth, make_requirement):
    for i in range(7):
        make_requirement(title=f"检索目标 {i}")
    r = client.get("/api/search?q=检索目标&limit=3", headers=auth("member"))
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["requirements"]) == 3
    assert body["counts"]["requirements"] == 7


def test_search_limit_clamped_to_min(client, auth, make_requirement):
    make_requirement(title="边界命中甲")
    make_requirement(title="边界命中乙")
    r = client.get("/api/search?q=边界命中&limit=0", headers=auth("member"))
    assert r.status_code == 200
    body = r.get_json()
    # clamp 下限为 1：至少返回 1 条（而非 0 条）。
    assert len(body["requirements"]) == 1
    assert body["counts"]["requirements"] == 2


def test_search_limit_clamped_to_max(client, auth, make_requirement):
    make_requirement(title="上限命中")
    r = client.get("/api/search?q=上限命中&limit=999", headers=auth("member"))
    assert r.status_code == 200
    body = r.get_json()
    # 超大 limit 不报错、行为等价上限 20；结构完整。
    assert body["counts"]["requirements"] == 1
    assert len(body["requirements"]) == 1
    assert "bugs" in body and "counts" in body


def test_search_escapes_like_wildcards(client, auth):
    """R2 真回归护栏：q=% 只应命中含字面 % 者。

    诱饵「进度良好」不含字面 %。若漏写 escape/漏转义，模式退化为 %%% 命中全部
    （诱饵也中）→ 断言 ==1 失败；转义后 %\\%% 仅命中「80% 覆盖率」→ 通过。
    """
    _post_req(client, auth, title="80% 覆盖率")
    _post_req(client, auth, title="进度良好")
    r = client.get("/api/search?q=%25", headers=auth("member"))  # %25 == 字面 '%'
    assert r.status_code == 200
    body = r.get_json()
    assert [x["title"] for x in body["requirements"]] == ["80% 覆盖率"]
    assert body["counts"]["requirements"] == 1


def test_search_no_hits_returns_empty_groups(client, auth, make_requirement):
    make_requirement(title="无关标题")
    r = client.get("/api/search?q=绝不命中的关键词", headers=auth("member"))
    assert r.status_code == 200
    body = r.get_json()
    assert body["requirements"] == []
    assert body["bugs"] == []
    assert body["documents"] == []
    assert body["counts"] == {"requirements": 0, "bugs": 0, "documents": 0}


def test_search_requires_auth(client):
    r = client.get("/api/search?q=登录")
    assert r.status_code == 401
