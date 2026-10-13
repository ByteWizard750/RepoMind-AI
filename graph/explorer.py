"""Read-only views of what is stored in Neo4j, for the Knowledge Graph tab.

Every view is a fixed set of Cypher queries run in read transactions; the
queries are returned with the result so the page can show exactly what was
asked of the database. Nothing here is rebuilt from the analysis in memory:
it is the graph as Neo4j holds it now (one repository at a time).
"""
import posixpath

# Per view: the labels to fetch (label, extra WHERE, ORDER BY, cap) and the relationship types between them.
VIEWS = {
    "code": {
        "title": "Code structure",
        "description": "Modules, the classes and functions they contain, and the IMPORTS and CALLS between them.",
        "labels": [("Module", "", "n.path", 400), ("Class", "", "n.module_path, n.name", 400),
                   ("Function", "", "n.module_path, n.name", 600)],
        "types": ["CONTAINS", "IMPORTS", "CALLS"],
    },
    "dependencies": {
        "title": "Module dependencies",
        "description": "Modules and the IMPORTS between them: the graph the architecture rules are checked on.",
        "labels": [("Module", "", "n.path", 800)],
        "types": ["IMPORTS"],
    },
    "history": {
        "title": "History",
        "description": "Developers, the commits they AUTHORED (most recent first), and the modules each commit MODIFIED.",
        "labels": [("Developer", "", "n.name", 100), ("Commit", "", "n.timestamp DESC", 250),
                   ("Module", "", "n.path", 400)],
        "types": ["AUTHORED", "MODIFIED"],
    },
    "temporal": {
        "title": "Time travel",
        "description": "History snapshots in order (NEXT), the commit each one is AT, the modules as they were "
                       "(HModule) and the imports between them, valid from one snapshot to another (H_IMPORTS).",
        "labels": [("Snapshot", "", "n.idx", 100), ("Commit", "(n)<-[:AT]-(:Snapshot)", "n.timestamp", 100),
                   ("HModule", "", "n.path", 400)],
        "types": ["NEXT", "AT", "H_IMPORTS"],
    },
    "decisions": {
        "title": "Decisions",
        "description": "Reconstructed decision records, the commits EVIDENCED_BY them and the modules they AFFECT. "
                       "Empty until the Decisions tab has finished.",
        "labels": [("Decision", "", "n.date", 50), ("Commit", "(n)<-[:EVIDENCED_BY]-(:Decision)", "n.timestamp", 200),
                   ("Module", "(n)<-[:AFFECTS]-(:Decision)", "n.path", 300)],
        "types": ["EVIDENCED_BY", "AFFECTS"],
    },
    "everything": {
        "title": "Everything",
        "description": "Every node type and relationship type together, capped per type.",
        "labels": [(label, "", "elementId(n)", 120) for label in
                   ("Module", "Class", "Function", "Commit", "Developer", "Snapshot", "HModule", "Decision")],
        "types": None,      # every type
    },
}

MAX_RELATIONSHIPS = 4000
MAX_NEIGHBOURS = 60
_LONG_TEXT = 300            # longer property values (JSON blobs, file lists) are cut for display

COUNTS_CYPHER = ["MATCH (n) RETURN head(labels(n)) AS label, count(*) AS count",
                 "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count"]
MODEL_CYPHER = ("MATCH (a)-[r]->(b) RETURN head(labels(a)) AS source, type(r) AS type, "
                "head(labels(b)) AS target, count(*) AS count")


def _props(entity) -> dict:
    out = {}
    for key, value in dict(entity).items():
        text = value if isinstance(value, (int, float, bool)) or value is None else str(value)
        if isinstance(text, str) and len(text) > _LONG_TEXT:
            text = text[:_LONG_TEXT] + "…"
        out[key] = text
    return out


def caption(label: str, props: dict) -> str:
    """The short name shown on a node."""
    if label in ("Module", "HModule"):
        return posixpath.basename(str(props.get("path", ""))) or "?"
    if label == "Function":
        return f"{props['class_name']}.{props.get('name')}" if props.get("class_name") else str(props.get("name"))
    if label == "Commit":
        return str(props.get("short", ""))
    if label == "Snapshot":
        return f"#{props.get('idx')} {props.get('short', '')}"
    if label == "Decision":
        title = str(props.get("title", ""))
        return title if len(title) <= 40 else title[:39] + "…"
    return str(props.get("name", label))


def _node(n) -> dict:
    label = next(iter(n.labels), "Node")
    props = _props(n)
    return {"id": n.element_id, "label": label, "caption": caption(label, props), "props": props}


def _edge(r) -> dict:
    return {"id": r.element_id, "type": r.type, "from": r.start_node.element_id, "to": r.end_node.element_id,
            "props": _props(r)}


def counts(session) -> dict:
    nodes = {r["label"]: r["count"] for r in session.execute_read(lambda tx: tx.run(COUNTS_CYPHER[0]).data())}
    rels = {r["type"]: r["count"] for r in session.execute_read(lambda tx: tx.run(COUNTS_CYPHER[1]).data())}
    return {"nodes": nodes, "relationships": rels}


def data_model(session) -> dict:
    """The schema as stored: one node per label, one edge per (label)-[TYPE]->(label) with its count."""
    totals = counts(session)
    rows = session.execute_read(lambda tx: tx.run(MODEL_CYPHER).data())
    nodes = [{"id": f"label:{label}", "label": label, "caption": f"{label}\n{count:,}",
              "props": {"label": label, "nodes": count}} for label, count in sorted(totals["nodes"].items())]
    edges = [{"id": f"type:{r['source']}:{r['type']}:{r['target']}", "type": r["type"],
              "from": f"label:{r['source']}", "to": f"label:{r['target']}",
              "caption": f"{r['type']} ({r['count']:,})", "props": {"type": r["type"], "relationships": r["count"]}}
             for r in rows]
    return {"view": "model", "title": "Data model",
            "description": "What kinds of nodes and relationships Neo4j holds, with how many of each.",
            "cypher": COUNTS_CYPHER + [MODEL_CYPHER], "nodes": nodes, "edges": edges, "truncated": {},
            "totals": totals}


def view(session, name: str) -> dict:
    if name == "model":
        return data_model(session)
    spec = VIEWS[name]
    queries, nodes, truncated = [], {}, {}
    totals = counts(session)
    for label, where, order, cap in spec["labels"]:
        query = (f"MATCH (n:{label}){' WHERE ' + where if where else ''} "
                 f"RETURN n ORDER BY {order} LIMIT $limit")
        queries.append(query.replace("$limit", str(cap)))
        found = session.execute_read(lambda tx, q=query, c=cap: [rec["n"] for rec in tx.run(q, limit=c)])
        for n in found:
            nodes.setdefault(n.element_id, _node(n))
        available = totals["nodes"].get(label, 0) if not where else None
        if available is not None and available > len(found):
            truncated[label] = {"shown": len(found), "total": available}
    ids = list(nodes)
    type_filter = "type(r) IN $types AND " if spec["types"] else ""
    rel_query = (f"MATCH (a) WHERE elementId(a) IN $ids MATCH (a)-[r]->(b) "
                 f"WHERE {type_filter}elementId(b) IN $ids RETURN r LIMIT $limit")
    queries.append(rel_query.replace("$types", str(spec["types"])).replace("$limit", str(MAX_RELATIONSHIPS)))
    rels = session.execute_read(lambda tx: [rec["r"] for rec in tx.run(
        rel_query, ids=ids, types=spec["types"] or [], limit=MAX_RELATIONSHIPS)])
    if len(rels) >= MAX_RELATIONSHIPS:
        truncated["relationships"] = {"shown": len(rels), "total": None}
    return {"view": name, "title": spec["title"], "description": spec["description"], "cypher": queries,
            "nodes": list(nodes.values()), "edges": [_edge(r) for r in rels], "truncated": truncated,
            "totals": totals}


NEIGHBOURS_CYPHER = "MATCH (n)-[r]-(m) WHERE elementId(n) = $id RETURN r, m LIMIT $limit"


def neighbours(session, node_id: str) -> dict:
    def read(tx):
        return [(rec["r"], rec["m"]) for rec in tx.run(NEIGHBOURS_CYPHER, id=node_id, limit=MAX_NEIGHBOURS + 1)]
    found = session.execute_read(read)
    more = len(found) > MAX_NEIGHBOURS
    found = found[:MAX_NEIGHBOURS]
    return {"cypher": [NEIGHBOURS_CYPHER.replace("$limit", str(MAX_NEIGHBOURS + 1))],
            "nodes": [_node(m) for _, m in found], "edges": [_edge(r) for r, _ in found], "more": more}
