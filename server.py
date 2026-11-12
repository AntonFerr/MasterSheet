from __future__ import annotations

import json
import math
import os
import base64
import binascii
import ast
import operator
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "masterficha.sqlite3"
MAX_BODY = 4_000_000
MAX_IMAGE_BYTES = 2_000_000


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize_db() -> None:
    with connect_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS rpgs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fichas (
                id TEXT PRIMARY KEY,
                rpg_id TEXT NOT NULL REFERENCES rpgs(id) ON DELETE RESTRICT,
                name TEXT NOT NULL,
                history TEXT NOT NULL DEFAULT '',
                attributes TEXT NOT NULL DEFAULT '[]',
                powers TEXT NOT NULL DEFAULT '[]',
                inventory TEXT NOT NULL DEFAULT '[]',
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS fichas_rpg_idx ON fichas(rpg_id);
            CREATE TABLE IF NOT EXISTS ficha_registros (
                id TEXT PRIMARY KEY,
                ficha_id TEXT NOT NULL REFERENCES fichas(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK (kind IN ('treino', 'missao', 'evento')),
                occurred_on TEXT NOT NULL,
                description TEXT NOT NULL,
                image_data TEXT NOT NULL,
                gains TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS registros_ficha_date_idx ON ficha_registros(ficha_id, occurred_on DESC);
        """)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: object, field: str, limit: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"O campo {field} deve ser texto.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"Preencha o campo {field}.")
    if len(value) > limit:
        raise ValueError(f"O campo {field} deve ter no máximo {limit} caracteres.")
    return value


def clean_rows(value: object, field: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError(f"A lista {field} é inválida (limite de 100 itens).")
    rows = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError(f"Há um item inválido em {field}.")
        if field == "attributes":
            name = clean_text(row.get("name", ""), "nome do atributo", 80, True)
            value_text = clean_text(row.get("value", ""), "valor do atributo", 120)
            rows.append({"name": name, "value": value_text})
        elif field == "powers":
            name = clean_text(row.get("name", ""), "nome do poder", 100, True)
            description = clean_text(row.get("description", ""), "descrição do poder", 1000)
            effects = row.get("effects", [])
            if not isinstance(effects, list) or len(effects) > 20:
                raise ValueError("Informe até 20 modificadores para cada poder.")
            clean_effects = []
            for effect in effects:
                if not isinstance(effect, dict):
                    raise ValueError("Há um modificador de atributo inválido.")
                attribute = clean_text(effect.get("attribute", ""), "atributo modificado", 80, True)
                operation = effect.get("operation")
                if operation not in ("add", "subtract", "multiply", "divide"):
                    raise ValueError("Escolha somar, subtrair, multiplicar ou dividir.")
                amount = effect.get("amount")
                if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0 or amount > 1_000_000 or not math.isfinite(amount):
                    raise ValueError("O valor do modificador deve ser maior que zero.")
                clean_effects.append({"attribute": attribute, "operation": operation, "amount": amount})
            rows.append({"name": name, "description": description, "effects": clean_effects})
        else:
            name = clean_text(row.get("name", ""), "nome do item", 100, True)
            quantity = clean_text(row.get("quantity", ""), "quantidade", 40)
            description = clean_text(row.get("description", ""), "descrição do item", 500)
            rows.append({"name": name, "quantity": quantity, "description": description})
    return rows


def validate_attribute_formulas(attributes: list[dict[str, str]]) -> None:
    """Validate arithmetic expressions and resolve parenthesized attribute references."""
    by_name = {row["name"].casefold(): row for row in attributes}
    if len(by_name) != len(attributes):
        raise ValueError("Os nomes dos atributos devem ser únicos.")
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                  ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
                  ast.UAdd: operator.pos}
    resolved: dict[str, float] = {}
    visiting: set[str] = set()

    def evaluate(name: str) -> float:
        key = name.casefold()
        if key in resolved:
            return resolved[key]
        if key in visiting:
            raise ValueError("As fórmulas dos atributos não podem formar dependências circulares.")
        visiting.add(key)
        expression = by_name[key]["value"].replace(",", ".")
        # A parenthesized word/name is an attribute reference. Parenthesized math remains math.
        expression = re.sub(r"\(([\wÀ-ÿ][\wÀ-ÿ ]*)\)", lambda match: str(evaluate(match.group(1).strip()))
                            if match.group(1).strip().casefold() in by_name else match.group(0), expression)
        try:
            tree = ast.parse(expression, mode="eval")
            def visit(node: ast.AST) -> float:
                if isinstance(node, ast.Expression): return visit(node.body)
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool): return float(node.value)
                if isinstance(node, ast.BinOp) and type(node.op) in operations:
                    left, right = visit(node.left), visit(node.right)
                    if isinstance(node.op, ast.Pow) and abs(right) > 100: raise ValueError("Expoente de fórmula muito grande.")
                    return operations[type(node.op)](left, right)
                if isinstance(node, ast.UnaryOp) and type(node.op) in operations: return operations[type(node.op)](visit(node.operand))
                raise ValueError("Use apenas números, referências entre parênteses e operações +, -, *, / e **.")
            result = visit(tree)
            if not isinstance(result, (int, float)) or abs(result) > 1e100: raise ValueError("O resultado da fórmula é inválido ou muito grande.")
        except (SyntaxError, ZeroDivisionError, OverflowError) as exc:
            raise ValueError(f"Fórmula inválida no atributo {name}.") from exc
        visiting.remove(key)
        resolved[key] = float(result)
        return float(result)

    for attribute in attributes:
        evaluate(attribute["name"])


def clean_tags(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("Informe até 20 tags.")
    tags = []
    for item in value:
        tag = clean_text(item, "tag", 30)
        if tag and tag.casefold() not in {t.casefold() for t in tags}:
            tags.append(tag)
    return tags


def ficha_payload(row: sqlite3.Row) -> dict:
    result = dict(row)
    for field in ("attributes", "powers", "inventory", "tags"):
        result[field] = json.loads(result[field])
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "MasterFicha/1.0"

    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY:
            raise ValueError("O conteúdo enviado está vazio ou excede o limite permitido.")
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("O conteúdo enviado não é um JSON válido.") from exc
        if not isinstance(value, dict):
            raise ValueError("O conteúdo enviado deve ser um objeto.")
        return value

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            with connect_db() as db:
                if path == "/api/rpgs":
                    rows = db.execute("""
                        SELECT r.id, r.name, r.created_at, COUNT(f.id) AS ficha_count
                        FROM rpgs r LEFT JOIN fichas f ON f.rpg_id = r.id
                        GROUP BY r.id ORDER BY r.name COLLATE NOCASE
                    """).fetchall()
                    return self.send_json(200, [dict(r) for r in rows])
                if path == "/api/fichas":
                    query = parse_qs(parsed.query)
                    search = query.get("q", [""])[0].strip()
                    rpg_id = query.get("rpg", [""])[0]
                    clauses, params = [], []
                    if search:
                        clauses.append("(f.name LIKE ? OR f.history LIKE ? OR f.tags LIKE ? OR f.id LIKE ? OR r.name LIKE ?)")
                        pattern = f"%{search}%"
                        params.extend([pattern] * 5)
                    if rpg_id:
                        clauses.append("f.rpg_id = ?")
                        params.append(rpg_id)
                    where = " WHERE " + " AND ".join(clauses) if clauses else ""
                    rows = db.execute("""
                        SELECT f.*, r.name AS rpg_name FROM fichas f JOIN rpgs r ON r.id = f.rpg_id
                    """ + where + " ORDER BY f.updated_at DESC", params).fetchall()
                    return self.send_json(200, [ficha_payload(r) for r in rows])
                if path.startswith("/api/fichas/") and path.endswith("/registros"):
                    ficha_id = path[len("/api/fichas/"):-len("/registros")].strip("/")
                    if not db.execute("SELECT 1 FROM fichas WHERE id = ?", (ficha_id,)).fetchone():
                        return self.send_json(404, {"error": "Ficha não encontrada."})
                    rows = db.execute("SELECT * FROM ficha_registros WHERE ficha_id = ? ORDER BY occurred_on DESC, created_at DESC", (ficha_id,)).fetchall()
                    result = []
                    for row in rows:
                        item = dict(row)
                        item["gains"] = json.loads(item["gains"])
                        result.append(item)
                    return self.send_json(200, result)
                if path.startswith("/api/fichas/"):
                    ficha_id = path.removeprefix("/api/fichas/")
                    row = db.execute("SELECT f.*, r.name AS rpg_name FROM fichas f JOIN rpgs r ON r.id = f.rpg_id WHERE f.id = ?", (ficha_id,)).fetchone()
                    if row is None:
                        return self.send_json(404, {"error": "Ficha não encontrada."})
                    return self.send_json(200, ficha_payload(row))
            return self.serve_static(path)
        except sqlite3.Error:
            self.send_json(500, {"error": "Não foi possível consultar os dados."})

    def do_POST(self) -> None:
        try:
            data = self.read_json()
            with connect_db() as db:
                if self.path.startswith("/api/fichas/") and self.path.endswith("/registros"):
                    ficha_id = self.path[len("/api/fichas/"):-len("/registros")].strip("/")
                    if not db.execute("SELECT 1 FROM fichas WHERE id = ?", (ficha_id,)).fetchone():
                        return self.send_json(404, {"error": "Ficha não encontrada."})
                    record = self.validate_record(data)
                    record_id = str(uuid.uuid4())
                    db.execute("""INSERT INTO ficha_registros
                        (id, ficha_id, kind, occurred_on, description, image_data, gains, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (record_id, ficha_id, record["kind"], record["occurred_on"], record["description"],
                         record["image_data"], json.dumps(record["gains"], ensure_ascii=False), now()))
                    return self.send_json(201, {"id": record_id, "ficha_id": ficha_id, **record})
                if self.path == "/api/rpgs":
                    name = clean_text(data.get("name", ""), "nome do RPG", 80, True)
                    rpg_id = str(uuid.uuid4())
                    db.execute("INSERT INTO rpgs(id, name, created_at) VALUES (?, ?, ?)", (rpg_id, name, now()))
                    return self.send_json(201, {"id": rpg_id, "name": name, "ficha_count": 0})
                if self.path == "/api/fichas":
                    ficha = self.validate_ficha(data)
                    if not db.execute("SELECT 1 FROM rpgs WHERE id = ?", (ficha["rpg_id"],)).fetchone():
                        return self.send_json(400, {"error": "Selecione um RPG cadastrado."})
                    ficha_id, timestamp = str(uuid.uuid4()), now()
                    db.execute("""INSERT INTO fichas
                        (id, rpg_id, name, history, attributes, powers, inventory, tags, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (ficha_id, ficha["rpg_id"], ficha["name"], ficha["history"],
                         json.dumps(ficha["attributes"], ensure_ascii=False), json.dumps(ficha["powers"], ensure_ascii=False),
                         json.dumps(ficha["inventory"], ensure_ascii=False), json.dumps(ficha["tags"], ensure_ascii=False), timestamp, timestamp))
                    row = db.execute("SELECT f.*, r.name AS rpg_name FROM fichas f JOIN rpgs r ON r.id=f.rpg_id WHERE f.id=?", (ficha_id,)).fetchone()
                    return self.send_json(201, ficha_payload(row))
            self.send_json(404, {"error": "Rota não encontrada."})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except sqlite3.IntegrityError as exc:
            message = "Já existe um RPG com esse nome." if "rpgs.name" in str(exc) else "Não foi possível salvar o registro."
            self.send_json(409, {"error": message})
        except sqlite3.Error:
            self.send_json(500, {"error": "Não foi possível salvar os dados."})

    def do_PUT(self) -> None:
        try:
            prefix = "/api/fichas/"
            if not self.path.startswith(prefix):
                return self.send_json(404, {"error": "Rota não encontrada."})
            ficha_id = self.path[len(prefix):]
            ficha = self.validate_ficha(self.read_json())
            with connect_db() as db:
                if not db.execute("SELECT 1 FROM rpgs WHERE id = ?", (ficha["rpg_id"],)).fetchone():
                    return self.send_json(400, {"error": "Selecione um RPG cadastrado."})
                cursor = db.execute("""UPDATE fichas SET rpg_id=?, name=?, history=?, attributes=?, powers=?, inventory=?, tags=?, updated_at=? WHERE id=?""",
                    (ficha["rpg_id"], ficha["name"], ficha["history"], json.dumps(ficha["attributes"], ensure_ascii=False),
                     json.dumps(ficha["powers"], ensure_ascii=False), json.dumps(ficha["inventory"], ensure_ascii=False),
                     json.dumps(ficha["tags"], ensure_ascii=False), now(), ficha_id))
                if cursor.rowcount == 0:
                    return self.send_json(404, {"error": "Ficha não encontrada."})
                row = db.execute("SELECT f.*, r.name AS rpg_name FROM fichas f JOIN rpgs r ON r.id=f.rpg_id WHERE f.id=?", (ficha_id,)).fetchone()
                self.send_json(200, ficha_payload(row))
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except sqlite3.Error:
            self.send_json(500, {"error": "Não foi possível atualizar a ficha."})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        try:
            with connect_db() as db:
                if path.startswith("/api/registros/"):
                    record_id = path.removeprefix("/api/registros/")
                    cursor = db.execute("DELETE FROM ficha_registros WHERE id = ?", (record_id,))
                    if cursor.rowcount == 0:
                        return self.send_json(404, {"error": "Registro não encontrado."})
                    return self.send_json(200, {"ok": True})
                if path.startswith("/api/fichas/"):
                    ficha_id = path.removeprefix("/api/fichas/")
                    cursor = db.execute("DELETE FROM fichas WHERE id = ?", (ficha_id,))
                    if cursor.rowcount == 0:
                        return self.send_json(404, {"error": "Ficha não encontrada."})
                    return self.send_json(200, {"ok": True})
                if path.startswith("/api/rpgs/"):
                    rpg_id = path.removeprefix("/api/rpgs/")
                    cursor = db.execute("DELETE FROM rpgs WHERE id = ?", (rpg_id,))
                    if cursor.rowcount == 0:
                        return self.send_json(404, {"error": "RPG não encontrado."})
                    return self.send_json(200, {"ok": True})
            self.send_json(404, {"error": "Rota não encontrada."})
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "Este RPG possui fichas. Remova ou mova as fichas antes de excluir o RPG."})
        except sqlite3.Error:
            self.send_json(500, {"error": "Não foi possível excluir o registro."})

    @staticmethod
    def validate_ficha(data: dict) -> dict:
        rpg_id = clean_text(data.get("rpg_id", ""), "RPG", 36, True)
        attributes = clean_rows(data.get("attributes", []), "attributes")
        validate_attribute_formulas(attributes)
        powers = clean_rows(data.get("powers", []), "powers")
        attribute_names = {attribute["name"].casefold() for attribute in attributes}
        for power in powers:
            for effect in power["effects"]:
                if effect["attribute"].casefold() not in attribute_names:
                    raise ValueError(f'O poder "{power["name"]}" usa o atributo "{effect["attribute"]}", que não está cadastrado na ficha.')
        return {
            "rpg_id": rpg_id,
            "name": clean_text(data.get("name", ""), "nome da ficha", 120, True),
            "history": clean_text(data.get("history", ""), "história", 10000),
            "attributes": attributes,
            "powers": powers,
            "inventory": clean_rows(data.get("inventory", []), "inventory"),
            "tags": clean_tags(data.get("tags", [])),
        }

    @staticmethod
    def validate_record(data: dict) -> dict:
        kind = data.get("kind")
        if kind not in ("treino", "missao", "evento"):
            raise ValueError("Escolha Treino, Missão ou Evento.")
        occurred_on = clean_text(data.get("occurred_on", ""), "data", 10, True)
        try:
            datetime.strptime(occurred_on, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Informe uma data válida.") from exc
        image_data = data.get("image_data")
        if not isinstance(image_data, str) or len(image_data) > 2_800_000:
            raise ValueError("Adicione uma imagem PNG, JPEG ou WebP de até 2 MB.")
        match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})", image_data)
        if not match:
            raise ValueError("A imagem precisa ser PNG, JPEG ou WebP.")
        try:
            image_bytes = base64.b64decode(match.group(2), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Não foi possível ler a imagem enviada.") from exc
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError("A imagem deve ter no máximo 2 MB.")
        mime = match.group(1)
        signatures = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff", "webp": b"RIFF"}
        if not image_bytes.startswith(signatures[mime]) or (mime == "webp" and image_bytes[8:12] != b"WEBP"):
            raise ValueError("O conteúdo do arquivo não corresponde ao formato da imagem.")
        gains = data.get("gains", [])
        if not isinstance(gains, list) or len(gains) > 20:
            raise ValueError("Informe até 20 ganhos de atributo por registro.")
        clean_gains = []
        for gain in gains:
            if not isinstance(gain, dict):
                raise ValueError("Há um ganho de atributo inválido.")
            attribute = clean_text(gain.get("attribute", ""), "atributo recebido", 80, True)
            amount = gain.get("amount")
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0 or amount > 1_000_000 or not math.isfinite(amount):
                raise ValueError("O valor de cada ganho deve ser maior que zero.")
            clean_gains.append({"attribute": attribute, "amount": amount})
        return {
            "kind": kind,
            "occurred_on": occurred_on,
            "description": clean_text(data.get("description", ""), "descrição", 3000, True),
            "image_data": image_data,
            "gains": clean_gains,
        }

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        file_path = (ROOT / relative).resolve()
        if ROOT not in file_path.parents or not file_path.is_file():
            return self.send_json(404, {"error": "Página não encontrada."})
        content_type = "text/html; charset=utf-8" if file_path.suffix == ".html" else "text/css; charset=utf-8" if file_path.suffix == ".css" else "text/javascript; charset=utf-8"
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        if os.environ.get("MASTERFICHA_ACCESS_LOG") == "1":
            super().log_message(format, *args)


if __name__ == "__main__":
    initialize_db()
    port = int(os.environ.get("PORT", "8000"))
    print(f"MasterFicha disponível em http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
