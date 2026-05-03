from flask import Flask, request, jsonify, g
import psycopg2
import os
import time
import redis
import json
from psycopg2 import pool
from contextlib import contextmanager
from datetime import datetime, timezone

db_pool = None
cache_client = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), decode_responses=True)
app = Flask(__name__)


def get_pool():
    global db_pool
    if db_pool is None:
        for _ in range(3):
            try:
                db_pool = pool.SimpleConnectionPool(
                    1, 20,
                    host=os.environ.get("DB_HOST", "localhost"),
                    database=os.environ.get("DB_NAME", "notes"),
                    user=os.environ.get("DB_USER", "postgres"),
                    password=os.environ.get("DB_PASSWORD", "postgres"),
                    connect_timeout=10
                )
                break
            except psycopg2.OperationalError as e:
                print(f"Failed to initialize database: {e}")
                time.sleep(2)
                continue
        if db_pool is None:
            raise Exception(f"Failed to initialize database")
    return db_pool

@contextmanager
def get_db_connection():
    conn = get_pool().getconn()
    try:
        yield conn
    finally:
        get_pool().putconn(conn)


def init_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE TABLE IF NOT EXISTS notes (id SERIAL PRIMARY KEY, text TEXT)")
            conn.commit()
            return
    except psycopg2.OperationalError as e:
        raise Exception(f"Failed to initialize database: {e}")
    

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200

@app.route("/notes", methods=["GET"])
def list_notes():
    cached_data = cache_client.get("notes:all")
    if cached_data:
        return jsonify(json.loads(cached_data))
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, text FROM notes ORDER BY id")
                rows = cur.fetchall()
        result = [{"id": r[0], "text": r[1], "created_at": datetime.now(timezone.utc)} for r in rows]
        cache_client.set("notes:all", json.dumps(result))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/notes", methods=["POST"])
def create_note():
    data = request.json
    text = data.get("text")
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO notes (text) VALUES (%s) RETURNING id", (text,))
                id = cur.fetchone()[0]
            conn.commit()
        cache_client.delete("notes:all")    
        return jsonify({"id": id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
   

@app.route("/notes/<int:id>", methods=["GET"])
def get_note(id):
    cached_data = cache_client.get(f"notes:{id}")
    if cached_data:
        data = json.loads(cached_data)
        if "error" in data:
            return jsonify(data), 404
        return jsonify(data)

    note = None    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, text FROM notes WHERE id = %s", (id,))
                note = cur.fetchone()
        if not note:
            # cache the error for 1 minute
            cache_client.setex(f"notes:{id}", 60, json.dumps({"error": "Note not found"}))
            return jsonify({"error": "Note not found"}), 404

        result = {"id": note[0], "text": note[1]}

        # cache the result
        cache_client.set(f"notes:{id}", json.dumps(result))

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/notes/<int:id>", methods=["DELETE"])
def delete_note(id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM notes WHERE id = %s RETURNING id", (id,))
                deleted_note = cur.fetchone()
                if not deleted_note:
                    conn.rollback()
                    return jsonify({"error": "Note not found"}), 404

                conn.commit()

        # delete the cached data        
        cache_client.delete(f"notes:{id}")
        cache_client.delete("notes:all")

        return jsonify({"message": "Note deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/notes/<int:id>", methods=["PUT"])
def update_note(id):
    data = request.json
    text = data.get("text")
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE notes SET text = %s WHERE id = %s RETURNING id", (text, id))
                updated_note = cur.fetchone()

                if not updated_note:
                    conn.rollback()
                    return jsonify({"error": "Note not found"}), 404

                conn.commit()

        cache_client.delete(f"notes:{id}")
        cache_client.delete("notes:all")

        return jsonify({"message": "Note updated"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    



if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)

