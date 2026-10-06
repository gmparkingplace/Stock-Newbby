"""Local public OHLCV cache. No credentials, account data or trade executions."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from threading import RLock


def revision(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def epoch(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('source-timezone-required')
    return stamp.timestamp()


class MarketStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=5)
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1, 2):
            self.db.close()
            raise ValueError('market-cache-schema-unsupported; backup required')
        # SQLite backup includes WAL content; backup must finish before migration.
        if version == 1:
            backup = path.with_name(path.name + '.schema1.bak')
            if backup.exists():
                backup = path.with_name(path.name + '.schema1.' + datetime.now().strftime('%Y%m%d%H%M%S%f') + '.bak')
            target = sqlite3.connect(backup)
            try:
                self.db.backup(target)
            finally:
                target.close()
        self.db.execute('PRAGMA journal_mode=WAL')
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS revisions (key TEXT, revision TEXT, value TEXT NOT NULL, PRIMARY KEY(key,revision))')
            self.db.execute('CREATE TABLE IF NOT EXISTS pattern_results (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS pattern_snapshots (id TEXT PRIMARY KEY, value TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS pattern_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, symbol TEXT NOT NULL, value TEXT NOT NULL)')
            self.db.execute('PRAGMA user_version=2')

    def get(self, key):
        with self.lock:
            row = self.db.execute('SELECT value FROM entries WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, value):
        # One transaction publishes an entire coherent adjusted history/snapshot.
        body = json.dumps(value, ensure_ascii=False, allow_nan=False)
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO entries VALUES (?,?)', (key, body))
            self.db.execute('INSERT OR REPLACE INTO revisions VALUES (?,?,?)', (key, value['dataRevision'], body))
            self.db.execute('DELETE FROM revisions WHERE key=? AND rowid NOT IN (SELECT rowid FROM revisions WHERE key=? ORDER BY rowid DESC LIMIT 10)', (key, key))

    def pattern_result(self, key):
        with self.lock:
            row = self.db.execute('SELECT value FROM pattern_results WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def pattern_publish(self, key, result, pairs):
        # Caller holds lock across reading previous result and reconciliation.
        with self.lock, self.db:
            for event, snapshot in pairs:
                cursor = self.db.execute('INSERT OR IGNORE INTO pattern_events(id,symbol,value) VALUES (?,?,?)',
                                         (event['eventId'], result['symbol'], json.dumps(event, ensure_ascii=False, allow_nan=False)))
                if cursor.rowcount:
                    self.db.execute('INSERT INTO pattern_snapshots VALUES (?,?)',
                                    (snapshot['snapshotId'], json.dumps(snapshot, ensure_ascii=False, allow_nan=False)))
                else:
                    # Repeated results must point at the actually retained immutable basis.
                    stored = self.db.execute('SELECT value FROM pattern_events WHERE id=?', (event['eventId'],)).fetchone()
                    event.clear(); event.update(json.loads(stored[0]))
            self.db.execute('INSERT OR REPLACE INTO pattern_results VALUES (?,?)',
                            (key, json.dumps(result, ensure_ascii=False, allow_nan=False)))

    def pattern_events(self, symbol=None, cursor=0, limit=100, with_symbol=False):
        with self.lock:
            query = 'SELECT seq,symbol,value FROM pattern_events WHERE seq>?'
            args = [cursor]
            if symbol:
                query += ' AND symbol=?'; args.append(symbol)
            query += ' ORDER BY seq LIMIT ?'; args.append(limit)
            return [dict(json.loads(body), cursor=seq, **({'symbol':code} if with_symbol else {})) for seq, code, body in self.db.execute(query, args)]

    def pattern_recent(self, symbol, limit=20, rule=None, reference=None):
        with self.lock:
            query='SELECT seq,value FROM pattern_events WHERE symbol=?'
            args=[symbol]
            if rule:
                query+=" AND json_extract(value,'$.ruleVersion')=?";args.append(rule)
            if reference:
                from pattern_window import start
                first="COALESCE(json_extract(value,'$.poleStartTime'),json_extract(value,'$.structureStartTime'),json_extract(value,'$.adjustmentStartTime'),json_extract(value,'$.anchorTime'),json_extract(value,'$.confirmedBarTime'),json_extract(value,'$.barTime'))"
                event="COALESCE(json_extract(value,'$.confirmedBarTime'),json_extract(value,'$.barTime'),"+first+")"
                query+=' AND '+first+'>=? AND '+first+'<='+event+' AND '+event+' BETWEEN ? AND ?'
                args.extend([start(reference),start(reference),reference])
            query+=' ORDER BY seq DESC LIMIT ?';args.append(limit)
            return [dict(json.loads(body),cursor=seq) for seq,body in self.db.execute(query,args)]

    def pattern_event(self, ident):
        with self.lock:
            row = self.db.execute('SELECT value FROM pattern_events WHERE id=?', (ident,)).fetchone()
            return json.loads(row[0]) if row else None

    def pattern_latest_date(self, symbol, timeframe='D'):
        with self.lock:
            row=self.db.execute("SELECT max(json_extract(value,'$.timeline[#-1].barTime')) FROM pattern_results WHERE json_extract(value,'$.symbol')=? AND COALESCE(json_extract(value,'$.timeframe'),'D')=?",(symbol,timeframe)).fetchone()
            return row[0] if row else None

    def pattern_snapshot(self, ident):
        with self.lock:
            row = self.db.execute('SELECT value FROM pattern_snapshots WHERE id=?', (ident,)).fetchone()
            return json.loads(row[0]) if row else None

    def close(self):
        with self.lock:
            self.db.close()
