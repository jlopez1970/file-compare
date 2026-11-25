#!/usr/bin/env python3
"""
file_compare.py - Herramienta de comparacion de archivos
Version: v01.00

Funciones:
  1. dupes    : encuentra archivos con exactamente el mismo contenido dentro de
                una carpeta y sus subcarpetas.
  2. compare  : compara dos carpetas (solo en A, solo en B, iguales, distintos).
  3. samename : encuentra dos o mas archivos con el mismo nombre y distinto
                contenido.
  4. CLI      : todo se puede correr desde la linea de comandos sin interfaz.
  5. GUI      : interfaz grafica (tkinter) con  `python file_compare.py gui`
                o ejecutando el script sin argumentos.

Solo usa la libreria estandar de Python 3.8+.

Ejemplos:
  python file_compare.py dupes ~/Documentos
  python file_compare.py dupes ~/Fotos --min-size 1024 --csv dupes.csv
  python file_compare.py compare ./carpetaA ./carpetaB --json resultado.json
  python file_compare.py samename ~/Proyectos --exclude "*.tmp" --exclude ".git"
  python file_compare.py gui
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import json
import os
import sys
import shutil
import threading
from collections import defaultdict
from datetime import datetime
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

__version__ = "v01.00"

CHUNK = 1024 * 1024          # 1 MB por lectura
PARTIAL = 64 * 1024          # 64 KB para el hash parcial

ProgressFn = Optional[Callable[[str], None]]

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".file_compare.json")
QUARANTINE_DIR = "_duplicados_eliminados"   # nunca se escanea
LOG_NAME = "registro.csv"
MAX_RECENT = 10

KEEP_CHOICES = {
    "oldest": "El mas antiguo (fecha de modificacion)",
    "newest": "El mas reciente (fecha de modificacion)",
    "shortest": "La ruta mas corta",
    "first": "El primero en orden alfabetico",
}


# --------------------------------------------------------------------------- #
#  Configuracion persistente (ultima seleccion de carpetas)
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except OSError as e:
        _warn(f"No se pudo guardar la configuracion en {CONFIG_PATH}: {e}")


def remember_folders(mode: str, folder_a: str, folder_b: str = "", **extra) -> None:
    """Guarda la ultima seleccion y la lista de carpetas recientes."""
    cfg = load_config()
    cfg.update({"mode": mode, "folder_a": folder_a}, **extra)
    if folder_b:
        cfg["folder_b"] = folder_b
    recent = [f for f in (folder_b, folder_a) if f] + cfg.get("recent", [])
    seen, out = set(), []
    for f in recent:
        if f not in seen:
            seen.add(f); out.append(f)
    cfg["recent"] = out[:MAX_RECENT]
    save_config(cfg)


# --------------------------------------------------------------------------- #
#  Utilidades de recorrido y hash
# --------------------------------------------------------------------------- #
@dataclass
class ScanOptions:
    exclude: List[str] = field(default_factory=list)
    include: List[str] = field(default_factory=list)   # vacio = todos los archivos
    include_hidden: bool = False
    follow_symlinks: bool = False
    min_size: int = 0
    ignore_case: bool = False   # para comparar nombres en "samename"


def split_patterns(text: str) -> List[str]:
    """Separa los patrones escritos en la GUI: por coma, punto y coma o salto de linea."""
    return [p.strip() for p in text.replace(";", ",").replace("\n", ",").split(",") if p.strip()]


def _compile_patterns(patterns: List[str]) -> List[Tuple[str, str]]:
    """Normaliza los patrones de exclusion. Devuelve (tipo, patron):
       'abs'  -> ruta absoluta (se compara con la ruta completa)
       'rel'  -> contiene '/' (se compara con la ruta relativa a la carpeta escaneada)
       'name' -> solo un nombre (se compara con el nombre del archivo o carpeta)
    Todo se compara sin distinguir mayusculas y con '/' como separador."""
    out = []
    for raw in patterns:
        p = os.path.expanduser(raw.strip().strip('"').strip("'")).replace("\\", "/")
        while len(p) > 1 and p.endswith("/"):
            p = p[:-1]
        if not p:
            continue
        p = p.lower()
        if os.path.isabs(p) or (len(p) > 2 and p[1] == ":"):   # /ruta o C:/ruta
            out.append(("abs", os.path.normpath(p).replace("\\", "/")))
        elif "/" in p:
            out.append(("rel", p[2:] if p.startswith("./") else p))
        else:
            out.append(("name", p))
    return out


def _matches(name: str, rel: str, full: str, pats: List[Tuple[str, str]]) -> bool:
    """True si el archivo o carpeta coincide con algun patron (sin distinguir mayusculas)."""
    name_l, rel_l, full_l = name.lower(), rel.replace(os.sep, "/").lower(), full.replace(os.sep, "/").lower()
    for kind, p in pats:
        if kind == "name" and fnmatch.fnmatchcase(name_l, p):
            return True
        if kind == "rel" and (fnmatch.fnmatchcase(rel_l, p) or fnmatch.fnmatchcase(rel_l, "*/" + p)):
            return True
        if kind == "abs" and fnmatch.fnmatchcase(full_l, p):
            return True
    return False


def _excluded(name: str, rel: str, full: str, opts: ScanOptions,
              pats: List[Tuple[str, str]]) -> bool:
    if not opts.include_hidden and name.startswith("."):
        return True
    return _matches(name, rel, full, pats)


def _included(rel: str, root: str, pats: List[Tuple[str, str]]) -> bool:
    """Filtro 'solo incluir': el archivo entra si el patron coincide con el archivo
    o con cualquiera de las carpetas que lo contienen. Sin patrones entra todo."""
    if not pats:
        return True
    parts = rel.split(os.sep)
    for i in range(len(parts), 0, -1):       # el archivo, luego cada carpeta padre
        sub = os.path.join(*parts[:i])
        if _matches(parts[i - 1], sub, os.path.join(root, sub), pats):
            return True
    return False


def walk_files(root: str, opts: ScanOptions, progress: ProgressFn = None) -> Iterable[str]:
    """Genera rutas absolutas de todos los archivos bajo root."""
    root = os.path.abspath(root)
    pats = _compile_patterns(opts.exclude)
    inc = _compile_patterns(opts.include)
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=opts.follow_symlinks,
                                                 onerror=lambda e: _warn(f"No se pudo leer: {e}")):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = [d for d in dirnames if d != QUARANTINE_DIR and not _excluded(
            d, os.path.join(rel_dir, d), os.path.join(dirpath, d), opts, pats)]
        for fn in filenames:
            rel_f = os.path.join(rel_dir, fn)
            # primero "solo incluir", despues "excluir" (la exclusion siempre gana)
            if not _included(rel_f, root, inc):
                continue
            if _excluded(fn, rel_f, os.path.join(dirpath, fn), opts, pats):
                continue
            path = os.path.join(dirpath, fn)
            if not opts.follow_symlinks and os.path.islink(path):
                continue
            if not os.path.isfile(path):
                continue
            count += 1
            if progress and count % 500 == 0:
                progress(f"Escaneados {count} archivos...")
            yield path


def file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


def hash_file(path: str, partial: bool = False) -> Optional[str]:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            if partial:
                h.update(f.read(PARTIAL))
            else:
                for block in iter(lambda: f.read(CHUNK), b""):
                    h.update(block)
    except OSError as e:
        _warn(f"No se pudo leer {path}: {e}")
        return None
    return h.hexdigest()


def _warn(msg: str) -> None:
    print(f"[aviso] {msg}", file=sys.stderr)


def _group_by_content(paths: List[str], progress: ProgressFn = None) -> Dict[str, List[str]]:
    """Agrupa rutas por contenido identico. Estrategia: tamano -> hash parcial -> hash completo.
    Devuelve {sha256: [rutas]} solo para grupos con 2+ archivos."""
    by_size: Dict[int, List[str]] = defaultdict(list)
    for p in paths:
        s = file_size(p)
        if s >= 0:
            by_size[s].append(p)

    result: Dict[str, List[str]] = {}
    candidates = [g for g in by_size.values() if len(g) > 1]
    total = sum(len(g) for g in candidates)
    done = 0
    for group in candidates:
        by_partial: Dict[str, List[str]] = defaultdict(list)
        for p in group:
            hp = hash_file(p, partial=True)
            if hp:
                by_partial[hp].append(p)
        for sub in by_partial.values():
            if len(sub) < 2:
                done += len(sub)
                continue
            by_full: Dict[str, List[str]] = defaultdict(list)
            for p in sub:
                hf = hash_file(p)
                done += 1
                if progress and done % 100 == 0:
                    progress(f"Comparando contenido {done}/{total}...")
                if hf:
                    by_full[hf].append(p)
            for hf, files in by_full.items():
                if len(files) > 1:
                    result[hf] = sorted(files)
    return result


# --------------------------------------------------------------------------- #
#  1. Duplicados
# --------------------------------------------------------------------------- #
def find_duplicates(root: str, opts: ScanOptions, progress: ProgressFn = None) -> List[dict]:
    paths = [p for p in walk_files(root, opts, progress) if file_size(p) >= opts.min_size]
    if progress:
        progress(f"{len(paths)} archivos encontrados. Buscando duplicados...")
    groups = _group_by_content(paths, progress)
    out = []
    for h, files in groups.items():
        size = file_size(files[0])
        out.append({"hash": h, "size": size, "count": len(files),
                    "wasted": size * (len(files) - 1), "files": files})
    out.sort(key=lambda g: g["wasted"], reverse=True)
    for i, g in enumerate(out, 1):
        g["group"] = i          # numero fijo, el mismo que se muestra en el reporte
    return out


def parse_group_list(text: str) -> set:
    """Convierte '1,3,5-7' en {1,3,5,6,7}."""
    out = set()
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


# --------------------------------------------------------------------------- #
#  1b. Limpiar duplicados
# --------------------------------------------------------------------------- #
def _mtime(p: str) -> float:
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def choose_keeper(files: List[str], keep: str) -> str:
    """Elige que archivo conservar de un grupo de duplicados."""
    if keep == "oldest":
        return min(files, key=lambda p: (_mtime(p), p))
    if keep == "newest":
        return max(files, key=lambda p: (_mtime(p), p))
    if keep == "shortest":
        return min(files, key=lambda p: (len(p), p))
    if keep == "first":
        return min(files)
    raise ValueError(f"Estrategia desconocida: {keep}")


def plan_cleanup(groups: List[dict], keep: str) -> List[dict]:
    """Devuelve el plan: que se conserva y que se elimina en cada grupo."""
    plan = []
    for i, g in enumerate(groups, 1):
        keeper = choose_keeper(g["files"], keep)
        plan.append({"group": g.get("group", i), "hash": g["hash"], "size": g["size"], "keep": keeper,
                     "remove": [f for f in g["files"] if f != keeper]})
    return plan


def clean_duplicates(groups: List[dict], root: str, keep: str = "oldest",
                     permanent: bool = False, progress: ProgressFn = None) -> dict:
    """Elimina los duplicados dejando un archivo por grupo.

    Por defecto (permanent=False) los archivos se MUEVEN a
    <root>/_duplicados_eliminados/<fecha_hora>/ conservando su ruta relativa,
    y se pueden restaurar con el comando 'restore'.
    Con permanent=True se borran definitivamente.
    Antes de eliminar cada archivo se vuelve a verificar su contenido."""
    root = os.path.abspath(root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    qdir = os.path.join(root, QUARANTINE_DIR, stamp)
    os.makedirs(qdir, exist_ok=True)
    log_path = os.path.join(qdir, LOG_NAME)

    removed, freed, errors = 0, 0, []
    plan = plan_cleanup(groups, keep)
    total = sum(len(p["remove"]) for p in plan)
    with open(log_path, "w", newline="", encoding="utf-8") as logf:
        log = csv.writer(logf)
        log.writerow(["accion", "ruta_original", "ruta_cuarentena", "conservado", "sha256"])
        for item in plan:
            if not os.path.isfile(item["keep"]) or hash_file(item["keep"]) != item["hash"]:
                errors.append(f"Se salto el grupo: el archivo a conservar cambio o no existe: {item['keep']}")
                continue
            for p in item["remove"]:
                try:
                    if not os.path.isfile(p) or hash_file(p) != item["hash"]:
                        errors.append(f"Se salto (cambio o no existe): {p}")
                        continue
                    size = file_size(p)
                    if permanent:
                        os.remove(p)
                        dest = ""
                    else:
                        rel = os.path.relpath(p, root)
                        dest = os.path.join(qdir, rel)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        shutil.move(p, dest)
                    log.writerow(["borrado" if permanent else "movido", p, dest, item["keep"], item["hash"]])
                    removed += 1
                    freed += max(size, 0)
                    if progress and removed % 50 == 0:
                        progress(f"Limpiando {removed}/{total}...")
                except OSError as e:
                    errors.append(f"No se pudo eliminar {p}: {e}")
    return {"removed": removed, "freed": freed, "errors": errors, "log": log_path,
            "quarantine": None if permanent else qdir, "permanent": permanent}


def restore_quarantine(qdir: str, progress: ProgressFn = None) -> dict:
    """Devuelve a su lugar original los archivos movidos por clean_duplicates."""
    log_path = os.path.join(qdir, LOG_NAME)
    if not os.path.isfile(log_path):
        raise FileNotFoundError(f"No se encontro {LOG_NAME} en {qdir}")
    restored, errors = 0, []
    with open(log_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["accion"] != "movido":
            continue
        src, dst = r["ruta_cuarentena"], r["ruta_original"]
        if not os.path.isfile(src):
            errors.append(f"Ya no esta en cuarentena: {src}")
        elif os.path.exists(dst):
            errors.append(f"Ya existe un archivo en la ruta original, no se sobrescribe: {dst}")
        else:
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                restored += 1
            except OSError as e:
                errors.append(f"No se pudo restaurar {dst}: {e}")
    return {"restored": restored, "errors": errors}


# --------------------------------------------------------------------------- #
#  2. Comparar dos carpetas
# --------------------------------------------------------------------------- #
def compare_folders(a: str, b: str, opts: ScanOptions, progress: ProgressFn = None) -> dict:
    a, b = os.path.abspath(a), os.path.abspath(b)
    files_a = {os.path.relpath(p, a): p for p in walk_files(a, opts, progress)}
    files_b = {os.path.relpath(p, b): p for p in walk_files(b, opts, progress)}

    only_a = sorted(set(files_a) - set(files_b))
    only_b = sorted(set(files_b) - set(files_a))
    common = sorted(set(files_a) & set(files_b))

    identical, different = [], []
    for i, rel in enumerate(common, 1):
        if progress and i % 100 == 0:
            progress(f"Comparando {i}/{len(common)}...")
        pa, pb = files_a[rel], files_b[rel]
        if file_size(pa) != file_size(pb) or hash_file(pa) != hash_file(pb):
            different.append(rel)
        else:
            identical.append(rel)

    # Archivos movidos/renombrados: mismo contenido, ruta distinta
    moved = []
    if only_a and only_b:
        if progress:
            progress("Buscando archivos movidos o renombrados...")
        hashes_b: Dict[Tuple[int, str], List[str]] = defaultdict(list)
        sizes_a = {file_size(files_a[r]) for r in only_a}
        for rel in only_b:
            s = file_size(files_b[rel])
            if s in sizes_a:
                h = hash_file(files_b[rel])
                if h:
                    hashes_b[(s, h)].append(rel)
        for rel in only_a:
            s = file_size(files_a[rel])
            key_candidates = [k for k in hashes_b if k[0] == s]
            if not key_candidates:
                continue
            h = hash_file(files_a[rel])
            if h and (s, h) in hashes_b:
                moved.append({"in_a": rel, "in_b": hashes_b[(s, h)]})

    return {"folder_a": a, "folder_b": b, "only_in_a": only_a, "only_in_b": only_b,
            "identical": identical, "different": different, "moved_or_renamed": moved}


# --------------------------------------------------------------------------- #
#  3. Mismo nombre, distinto contenido
# --------------------------------------------------------------------------- #
def same_name_diff_content(root: str, opts: ScanOptions, progress: ProgressFn = None) -> List[dict]:
    by_name: Dict[str, List[str]] = defaultdict(list)
    for p in walk_files(root, opts, progress):
        name = os.path.basename(p)
        by_name[name.lower() if opts.ignore_case else name].append(p)

    out = []
    groups = [(n, ps) for n, ps in by_name.items() if len(ps) > 1]
    for i, (name, paths) in enumerate(groups, 1):
        if progress and i % 50 == 0:
            progress(f"Revisando nombres {i}/{len(groups)}...")
        versions: Dict[str, List[str]] = defaultdict(list)
        for p in paths:
            h = hash_file(p)
            if h:
                versions[h].append(p)
        if len(versions) > 1:   # hay al menos dos contenidos distintos
            out.append({
                "name": os.path.basename(paths[0]),
                "versions": len(versions),
                "files": [{"path": p, "size": file_size(p), "hash": h[:12],
                           "modified": os.path.getmtime(p)}
                          for h, ps in versions.items() for p in sorted(ps)],
            })
    out.sort(key=lambda g: g["name"].lower())
    return out


# --------------------------------------------------------------------------- #
#  Formato y exportacion
# --------------------------------------------------------------------------- #
def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def report_dupes(groups: List[dict]) -> str:
    if not groups:
        return "No se encontraron archivos duplicados."
    lines = []
    wasted = sum(g["wasted"] for g in groups)
    lines.append(f"{len(groups)} grupos de duplicados - espacio recuperable: {human(wasted)}\n")
    for i, g in enumerate(groups, 1):
        lines.append(f"Grupo {i}: {g['count']} archivos de {human(g['size'])} (sha256 {g['hash'][:12]})")
        lines += [f"    {f}" for f in g["files"]]
        lines.append("")
    return "\n".join(lines)


def report_plan(plan: List[dict], keep: str, permanent: bool, skipped: Iterable[int] = ()) -> str:
    n = sum(len(p["remove"]) for p in plan)
    size = sum(p["size"] * len(p["remove"]) for p in plan)
    accion = "BORRAR DEFINITIVAMENTE" if permanent else f"MOVER a '{QUARANTINE_DIR}'"
    lines = [f"Plan de limpieza - se conserva: {KEEP_CHOICES[keep].lower()}",
             f"Se van a {accion} {n} archivos ({human(size)})."]
    skipped = sorted(skipped)
    if skipped:
        lines.append(f"Grupos omitidos (no se tocan): {', '.join(map(str, skipped))}")
    lines.append("")
    for p in plan:
        lines.append(f"Grupo {p['group']}:")
        lines.append(f"    CONSERVAR  {p['keep']}")
        lines += [f"    ELIMINAR   {f}" for f in p["remove"]]
    return "\n".join(lines)


def report_compare(r: dict) -> str:
    lines = [f"A: {r['folder_a']}", f"B: {r['folder_b']}", "",
             f"Identicos: {len(r['identical'])}   Distintos: {len(r['different'])}   "
             f"Solo en A: {len(r['only_in_a'])}   Solo en B: {len(r['only_in_b'])}   "
             f"Movidos/renombrados: {len(r['moved_or_renamed'])}", ""]
    for title, key in (("DISTINTOS (misma ruta, distinto contenido)", "different"),
                       ("SOLO EN A", "only_in_a"), ("SOLO EN B", "only_in_b")):
        if r[key]:
            lines.append(f"== {title} ==")
            lines += [f"    {x}" for x in r[key]]
            lines.append("")
    if r["moved_or_renamed"]:
        lines.append("== MOVIDOS / RENOMBRADOS (mismo contenido) ==")
        for m in r["moved_or_renamed"]:
            lines.append(f"    A:{m['in_a']}  ->  B:{', '.join(m['in_b'])}")
    return "\n".join(lines)


def report_samename(groups: List[dict]) -> str:
    if not groups:
        return "No hay archivos con el mismo nombre y distinto contenido."
    lines = [f"{len(groups)} nombres con contenidos distintos\n"]
    for g in groups:
        lines.append(f"{g['name']}  ({g['versions']} versiones distintas)")
        for f in g["files"]:
            lines.append(f"    [{f['hash']}] {human(f['size']):>10}  {f['path']}")
        lines.append("")
    return "\n".join(lines)


def export(mode: str, data, json_path: Optional[str], csv_path: Optional[str]) -> None:
    if json_path:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"JSON guardado en {json_path}", file=sys.stderr)
    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if mode == "dupes":
                w.writerow(["grupo", "sha256", "tamano_bytes", "ruta"])
                for i, g in enumerate(data, 1):
                    for p in g["files"]:
                        w.writerow([i, g["hash"], g["size"], p])
            elif mode == "compare":
                w.writerow(["estado", "ruta_relativa", "detalle"])
                for key, label in (("identical", "identico"), ("different", "distinto"),
                                   ("only_in_a", "solo_en_A"), ("only_in_b", "solo_en_B")):
                    for rel in data[key]:
                        w.writerow([label, rel, ""])
                for m in data["moved_or_renamed"]:
                    w.writerow(["movido", m["in_a"], "; ".join(m["in_b"])])
            elif mode == "samename":
                w.writerow(["nombre", "hash", "tamano_bytes", "ruta"])
                for g in data:
                    for f_ in g["files"]:
                        w.writerow([g["name"], f_["hash"], f_["size"], f_["path"]])
        print(f"CSV guardado en {csv_path}", file=sys.stderr)


# --------------------------------------------------------------------------- #
#  4. CLI
# --------------------------------------------------------------------------- #
def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--exclude", action="append", default=[], metavar="PATRON",
                   help="Excluir archivos/carpetas que coincidan (ej. '*.tmp', '.git'). Repetible.")
    p.add_argument("--include", "--only", action="append", default=[], metavar="PATRON", dest="include",
                   help="Solo buscar archivos que coincidan (ej. '*.jpg', 'Fotos'). Repetible. "
                        "Se combina con --exclude: primero se incluye, despues se excluye.")
    p.add_argument("--include-hidden", action="store_true", help="Incluir archivos ocultos (.*)")
    p.add_argument("--follow-symlinks", action="store_true", help="Seguir enlaces simbolicos")
    p.add_argument("--json", metavar="ARCHIVO", help="Exportar resultado a JSON")
    p.add_argument("--csv", metavar="ARCHIVO", help="Exportar resultado a CSV")
    p.add_argument("-q", "--quiet", action="store_true", help="No mostrar progreso")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Herramienta para comparar archivos y carpetas. Sin argumentos abre la interfaz grafica.")
    ap.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd")

    d = sub.add_parser("dupes", help="Archivos con contenido identico en una carpeta (y subcarpetas)")
    d.add_argument("folder")
    d.add_argument("--min-size", type=int, default=1, metavar="BYTES",
                   help="Ignorar archivos menores a este tamano (default 1: ignora vacios)")
    d.add_argument("--clean", action="store_true",
                   help=f"Limpiar duplicados: deja un archivo por grupo y mueve el resto a "
                        f"<carpeta>/{QUARANTINE_DIR}/<fecha_hora>/")
    d.add_argument("--keep", choices=list(KEEP_CHOICES), default="oldest",
                   help="Que archivo conservar en cada grupo (default: oldest)")
    d.add_argument("--permanent", action="store_true",
                   help="Con --clean: borrar definitivamente en vez de mover a cuarentena")
    d.add_argument("--dry-run", action="store_true",
                   help="Con --clean: solo mostrar el plan, sin eliminar nada")
    d.add_argument("--skip-groups", metavar="LISTA", default="",
                   help="Con --clean: grupos que NO se limpian, con el numero del reporte. "
                        "Ej: '2,5' o '3-7,10'")
    d.add_argument("-y", "--yes", action="store_true",
                   help="Con --clean: no pedir confirmacion")
    _add_common(d)

    c = sub.add_parser("compare", help="Comparar dos carpetas")
    c.add_argument("folder_a")
    c.add_argument("folder_b")
    _add_common(c)

    s = sub.add_parser("samename", help="Archivos con el mismo nombre y distinto contenido")
    s.add_argument("folder")
    s.add_argument("--ignore-case", action="store_true", help="Tratar 'Foto.JPG' y 'foto.jpg' como el mismo nombre")
    _add_common(s)

    r = sub.add_parser("restore", help="Restaurar archivos movidos por 'dupes --clean'")
    r.add_argument("quarantine_folder",
                   help=f"Carpeta de cuarentena, ej. <carpeta>/{QUARANTINE_DIR}/20261120_133000")

    sub.add_parser("gui", help="Abrir la interfaz grafica")
    return ap


def _confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        print("No hay terminal interactiva para confirmar; usa --yes.", file=sys.stderr)
        return False
    return input(f"{prompt} [s/N]: ").strip().lower() in ("s", "si", "sí", "y", "yes")


def _check_dir(path: str) -> None:
    if not os.path.isdir(path):
        sys.exit(f"Error: '{path}' no es una carpeta valida.")


def main_cli(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd in (None, "gui"):
        return run_gui()

    if args.cmd == "restore":
        _check_dir(args.quarantine_folder)
        res = restore_quarantine(args.quarantine_folder)
        print(f"Restaurados: {res['restored']}")
        for e in res["errors"]:
            _warn(e)
        return 0 if not res["errors"] else 1

    opts = ScanOptions(exclude=args.exclude, include=args.include, include_hidden=args.include_hidden,
                       follow_symlinks=args.follow_symlinks,
                       min_size=getattr(args, "min_size", 0),
                       ignore_case=getattr(args, "ignore_case", False))
    progress = None if args.quiet else (lambda m: print(m, file=sys.stderr))

    if args.cmd == "dupes":
        _check_dir(args.folder)
        remember_folders("dupes", os.path.abspath(args.folder))
        data = find_duplicates(args.folder, opts, progress)
        if not args.clean:
            print(report_dupes(data))
        else:
            export(args.cmd, data, args.json, args.csv)
            if not data:
                print(report_dupes(data))
                return 0
            try:
                skip = parse_group_list(args.skip_groups)
            except ValueError:
                sys.exit(f"Error: --skip-groups invalido: '{args.skip_groups}'. Usa por ejemplo '2,5' o '3-7'.")
            fuera = sorted(n for n in skip if not 1 <= n <= len(data))
            if fuera:
                _warn(f"Estos grupos no existen y se ignoran: {', '.join(map(str, fuera))}")
            skip -= set(fuera)
            data = [g for g in data if g["group"] not in skip]
            if not data:
                print("Todos los grupos estan omitidos. No hay nada que limpiar.")
                return 0
            print(report_plan(plan_cleanup(data, args.keep), args.keep, args.permanent, skip))
            if args.dry_run:
                print("\n(--dry-run: no se elimino nada)")
                return 0
            msg = ("Los archivos se BORRARAN DEFINITIVAMENTE. ¿Continuar?" if args.permanent
                   else "¿Continuar?")
            if not args.yes and not _confirm("\n" + msg):
                print("Cancelado. No se elimino nada.")
                return 1
            res = clean_duplicates(data, args.folder, args.keep, args.permanent, progress)
            print(f"\nEliminados: {res['removed']} archivos - espacio liberado: {human(res['freed'])}")
            if res["quarantine"]:
                print(f"Movidos a: {res['quarantine']}")
                print(f"Para deshacer: python {os.path.basename(sys.argv[0])} restore \"{res['quarantine']}\"")
            print(f"Registro: {res['log']}")
            for e in res["errors"]:
                _warn(e)
            return 0
    elif args.cmd == "compare":
        _check_dir(args.folder_a); _check_dir(args.folder_b)
        remember_folders("compare", os.path.abspath(args.folder_a), os.path.abspath(args.folder_b))
        data = compare_folders(args.folder_a, args.folder_b, opts, progress)
        print(report_compare(data))
    else:
        _check_dir(args.folder)
        remember_folders("samename", os.path.abspath(args.folder))
        data = same_name_diff_content(args.folder, opts, progress)
        print(report_samename(data))

    export(args.cmd, data, args.json, args.csv)
    return 0


# --------------------------------------------------------------------------- #
#  5. GUI (tkinter)
# --------------------------------------------------------------------------- #
def run_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        print("tkinter no esta disponible. Instalalo (ej. 'sudo apt install python3-tk') "
              "o usa el modo linea de comandos: python file_compare.py -h", file=sys.stderr)
        return 1

    root = tk.Tk()
    root.title(f"File Comparison Tool {__version__}")
    root.geometry("1000x650")

    cfg = load_config()   # ultima seleccion guardada
    mode = tk.StringVar(value=cfg.get("mode", "dupes"))
    folder_a = tk.StringVar(value=cfg.get("folder_a", ""))
    folder_b = tk.StringVar(value=cfg.get("folder_b", ""))
    exclude = tk.StringVar(value=cfg.get("exclude", ".git, __pycache__"))
    include = tk.StringVar(value=cfg.get("include", ""))
    hidden = tk.BooleanVar(value=cfg.get("include_hidden", False))
    ignore_case = tk.BooleanVar(value=cfg.get("ignore_case", False))
    status = tk.StringVar(value="Listo." if not cfg.get("folder_a") else "Listo. Se cargo la ultima seleccion de carpetas.")
    state = {"data": None, "mode": None, "folder": None}

    # ---- controles superiores
    top = ttk.Frame(root, padding=8); top.pack(fill="x")
    ttk.Label(top, text="Modo:").grid(row=0, column=0, sticky="w")
    modes = [("Duplicados (mismo contenido)", "dupes"), ("Comparar dos carpetas", "compare"),
             ("Mismo nombre, distinto contenido", "samename")]
    for i, (txt, val) in enumerate(modes):
        ttk.Radiobutton(top, text=txt, variable=mode, value=val,
                        command=lambda: _toggle()).grid(row=0, column=i + 1, sticky="w", padx=4)

    def pick(var):
        start = var.get() if os.path.isdir(var.get()) else os.path.expanduser("~")
        d = filedialog.askdirectory(initialdir=start)
        if d:
            var.set(d)

    recent = cfg.get("recent", [])
    ttk.Label(top, text="Carpeta A:").grid(row=1, column=0, sticky="w", pady=2)
    ent_a = ttk.Combobox(top, textvariable=folder_a, values=recent, width=80)
    ent_a.grid(row=1, column=1, columnspan=3, sticky="we")
    ttk.Button(top, text="Elegir...", command=lambda: pick(folder_a)).grid(row=1, column=4)
    lbl_b = ttk.Label(top, text="Carpeta B:")
    ent_b = ttk.Combobox(top, textvariable=folder_b, values=recent, width=80)
    btn_b = ttk.Button(top, text="Elegir...", command=lambda: pick(folder_b))
    lbl_b.grid(row=2, column=0, sticky="w", pady=2)
    ent_b.grid(row=2, column=1, columnspan=3, sticky="we")
    btn_b.grid(row=2, column=4)

    ttk.Label(top, text="Solo incluir:").grid(row=3, column=0, sticky="w", pady=2)
    ttk.Entry(top, textvariable=include, width=40).grid(row=3, column=1, sticky="we")
    ttk.Label(top, text="vacio = todos  (ej. *.jpg, *.png; Fotos)", foreground="#666"
              ).grid(row=3, column=2, columnspan=2, sticky="w", padx=6)
    ttk.Label(top, text="Excluir:").grid(row=4, column=0, sticky="w", pady=2)
    ttk.Entry(top, textvariable=exclude, width=40).grid(row=4, column=1, sticky="we")
    ttk.Checkbutton(top, text="Incluir ocultos", variable=hidden).grid(row=4, column=2, sticky="w", padx=6)
    chk_case = ttk.Checkbutton(top, text="Ignorar mayusculas en nombres", variable=ignore_case)
    chk_case.grid(row=4, column=3, sticky="w")
    top.columnconfigure(1, weight=1)

    btns = ttk.Frame(root, padding=(8, 0)); btns.pack(fill="x")
    run_btn = ttk.Button(btns, text="Ejecutar", command=lambda: _run())
    run_btn.pack(side="left")
    ttk.Button(btns, text="Exportar CSV", command=lambda: _export("csv")).pack(side="left", padx=4)
    ttk.Button(btns, text="Exportar JSON", command=lambda: _export("json")).pack(side="left")
    ttk.Button(btns, text="Abrir ubicacion", command=lambda: _open_selected()).pack(side="left", padx=4)
    clean_btn = ttk.Button(btns, text="Limpiar duplicados...", command=lambda: _clean_dialog())
    clean_btn.pack(side="left", padx=(12, 4))
    ttk.Button(btns, text="Restaurar...", command=lambda: _restore()).pack(side="left")
    bar = ttk.Progressbar(btns, mode="indeterminate", length=200); bar.pack(side="right")

    # ---- resultados
    frame = ttk.Frame(root, padding=8); frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(frame, columns=("info", "size"), show="tree headings")
    tree.heading("#0", text="Resultado"); tree.heading("info", text="Detalle"); tree.heading("size", text="Tamano")
    tree.column("#0", width=600); tree.column("info", width=250); tree.column("size", width=100, anchor="e")
    vs = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vs.set)
    tree.pack(side="left", fill="both", expand=True); vs.pack(side="right", fill="y")
    ttk.Label(root, textvariable=status, padding=(8, 2)).pack(fill="x")

    def _toggle():
        is_cmp = mode.get() == "compare"
        for w in (lbl_b, ent_b, btn_b):
            w.state(["!disabled"] if is_cmp else ["disabled"])
        chk_case.state(["!disabled"] if mode.get() == "samename" else ["disabled"])
        has_dupes = state["mode"] == "dupes" and bool(state["data"]) and mode.get() == "dupes"
        clean_btn.state(["!disabled"] if has_dupes else ["disabled"])
    _toggle()

    def _progress(msg):
        root.after(0, status.set, msg)

    def _run():
        a, b, m = folder_a.get().strip(), folder_b.get().strip(), mode.get()
        if not os.path.isdir(a) or (m == "compare" and not os.path.isdir(b)):
            messagebox.showerror("Error", "Selecciona carpeta(s) valida(s).")
            return
        opts = ScanOptions(exclude=split_patterns(exclude.get()), include=split_patterns(include.get()),
                           include_hidden=hidden.get(), ignore_case=ignore_case.get(),
                           min_size=1 if m == "dupes" else 0)
        a_abs = os.path.abspath(a)
        b_abs = os.path.abspath(b) if m == "compare" else ""
        remember_folders(m, a_abs, b_abs, exclude=exclude.get(), include=include.get(),
                         include_hidden=hidden.get(), ignore_case=ignore_case.get())
        new_recent = load_config().get("recent", [])
        ent_a.configure(values=new_recent); ent_b.configure(values=new_recent)
        state["folder"] = a_abs
        run_btn.state(["disabled"]); bar.start(10); tree.delete(*tree.get_children())

        def work():
            try:
                if m == "dupes":
                    data = find_duplicates(a, opts, _progress)
                elif m == "compare":
                    data = compare_folders(a, b, opts, _progress)
                else:
                    data = same_name_diff_content(a, opts, _progress)
                root.after(0, _show, m, data)
            except Exception as e:  # noqa: BLE001
                root.after(0, messagebox.showerror, "Error", str(e))
            finally:
                root.after(0, lambda: (bar.stop(), run_btn.state(["!disabled"])))
        threading.Thread(target=work, daemon=True).start()

    def _show(m, data):
        state["data"], state["mode"] = data, m
        if m == "dupes":
            wasted = sum(g["wasted"] for g in data)
            for i, g in enumerate(data, 1):
                node = tree.insert("", "end", text=f"Grupo {i} - {g['count']} copias",
                                   values=(f"sha256 {g['hash'][:12]}", human(g["size"])), open=True)
                for f in g["files"]:
                    tree.insert(node, "end", text=f, values=("", human(g["size"])))
            status.set(f"{len(data)} grupos de duplicados. Espacio recuperable: {human(wasted)}")
        elif m == "compare":
            sections = [("Distintos", data["different"], data["folder_a"]),
                        ("Solo en A", data["only_in_a"], data["folder_a"]),
                        ("Solo en B", data["only_in_b"], data["folder_b"]),
                        ("Identicos", data["identical"], data["folder_a"])]
            for title, items, base in sections:
                node = tree.insert("", "end", text=f"{title} ({len(items)})", open=title != "Identicos")
                for rel in items:
                    p = os.path.join(base, rel)
                    tree.insert(node, "end", text=p, values=(rel, human(max(file_size(p), 0))))
            node = tree.insert("", "end", text=f"Movidos/renombrados ({len(data['moved_or_renamed'])})", open=True)
            for mv in data["moved_or_renamed"]:
                tree.insert(node, "end", text=os.path.join(data["folder_a"], mv["in_a"]),
                            values=("-> " + ", ".join(mv["in_b"]), ""))
            status.set(f"Identicos {len(data['identical'])} | Distintos {len(data['different'])} | "
                       f"Solo A {len(data['only_in_a'])} | Solo B {len(data['only_in_b'])}")
        else:
            for g in data:
                node = tree.insert("", "end", text=g["name"], values=(f"{g['versions']} versiones", ""), open=True)
                for f in g["files"]:
                    tree.insert(node, "end", text=f["path"], values=(f"hash {f['hash']}", human(f["size"])))
            status.set(f"{len(data)} nombres con contenidos distintos.")
        _toggle()

    def _clean_dialog():
        groups, folder = state["data"], state["folder"]
        if state["mode"] != "dupes" or not groups:
            messagebox.showinfo("Limpiar", "Primero busca duplicados en modo 'Duplicados'.")
            return
        dlg = tk.Toplevel(root); dlg.title("Limpiar duplicados"); dlg.geometry("900x520")
        dlg.transient(root); dlg.grab_set()
        keep = tk.StringVar(value=load_config().get("keep", "oldest"))
        permanent = tk.BooleanVar(value=False)
        summary = tk.StringVar()

        opt = ttk.Frame(dlg, padding=8); opt.pack(fill="x")
        ttk.Label(opt, text="Conservar en cada grupo:").grid(row=0, column=0, sticky="w")
        labels = {v: k for k, v in KEEP_CHOICES.items()}
        cb = ttk.Combobox(opt, values=list(KEEP_CHOICES.values()), state="readonly", width=45)
        cb.set(KEEP_CHOICES[keep.get()]); cb.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Radiobutton(opt, text=f"Mover a '{QUARANTINE_DIR}' (se puede restaurar)",
                        variable=permanent, value=False).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(opt, text="Borrar definitivamente (no se puede deshacer)",
                        variable=permanent, value=True).grid(row=2, column=0, columnspan=2, sticky="w")

        # ---- barra de seleccion de grupos
        sel_bar = ttk.Frame(dlg, padding=(8, 4)); sel_bar.pack(fill="x")
        ttk.Label(sel_bar, text="Clic en un grupo (o barra espaciadora) para incluirlo u omitirlo:"
                  ).pack(side="left")
        ttk.Button(sel_bar, text="Desmarcar todos", command=lambda: set_all(False)).pack(side="right")
        ttk.Button(sel_bar, text="Marcar todos", command=lambda: set_all(True)).pack(side="right", padx=4)

        pf = ttk.Frame(dlg, padding=(8, 0)); pf.pack(fill="both", expand=True)
        pv = ttk.Treeview(pf, columns=("accion",), show="tree headings", selectmode="extended")
        pv.heading("#0", text="Archivo"); pv.heading("accion", text="Accion")
        pv.column("#0", width=720); pv.column("accion", width=120)
        ps = ttk.Scrollbar(pf, orient="vertical", command=pv.yview); pv.configure(yscrollcommand=ps.set)
        pv.pack(side="left", fill="both", expand=True); ps.pack(side="right", fill="y")
        pv.tag_configure("keep", foreground="#1a7f37"); pv.tag_configure("del", foreground="#b42318")
        pv.tag_configure("skip", foreground="#8a8a8a")
        pv.tag_configure("group_on", font=("TkDefaultFont", 0, "bold"))
        pv.tag_configure("group_off", foreground="#8a8a8a")

        skipped: set = set()        # hashes de los grupos omitidos
        items: Dict[str, dict] = {}  # hash -> {"node", "plan"}
        node_hash: Dict[str, str] = {}

        def paint(h):
            """Actualiza un grupo en la vista previa segun este marcado u omitido."""
            it, p = items[h], items[h]["plan"]
            on = h not in skipped
            n_copies = len(p["remove"]) + 1
            label = (f"{'☑' if on else '☐'}  Grupo {p['group']}  -  {n_copies} copias de {human(p['size'])}"
                     + ("" if on else "   (omitido)"))
            pv.item(it["node"], text=label, values=("LIMPIAR" if on else "OMITIR",),
                    tags=("group_on" if on else "group_off",))
            pv.item(it["keep"], values=("CONSERVAR" if on else "SIN CAMBIOS",), tags=("keep" if on else "skip",))
            for r in it["remove"]:
                pv.item(r, values=("ELIMINAR" if on else "SIN CAMBIOS",), tags=("del" if on else "skip",))

        def update_summary():
            active = [items[h]["plan"] for h in items if h not in skipped]
            n = sum(len(p["remove"]) for p in active)
            size = sum(p["size"] * len(p["remove"]) for p in active)
            omit = len(items) - len(active)
            txt = f"Se eliminaran {n} archivos y se liberaran {human(size)}."
            if omit:
                txt += f"   Grupos omitidos: {omit} de {len(items)}."
            summary.set(txt)
            state["plan_n"] = n
            clean_ok.state(["!disabled"] if n else ["disabled"])

        def refresh(*_):
            keep.set(labels[cb.get()])
            pv.delete(*pv.get_children()); items.clear(); node_hash.clear()
            for p in plan_cleanup(groups, keep.get()):
                node = pv.insert("", "end", open=True)
                k = pv.insert(node, "end", text=p["keep"])
                rs = [pv.insert(node, "end", text=f) for f in p["remove"]]
                items[p["hash"]] = {"node": node, "keep": k, "remove": rs, "plan": p}
                node_hash[node] = p["hash"]
                paint(p["hash"])
            update_summary()

        def toggle(nodes):
            for node in nodes:
                h = node_hash.get(node) or node_hash.get(pv.parent(node))
                if h:
                    skipped.symmetric_difference_update({h})
                    paint(h)
            update_summary()

        def set_all(on):
            skipped.clear() if on else skipped.update(items)
            for h in items:
                paint(h)
            update_summary()

        def on_click(event):
            row = pv.identify_row(event.y)
            # clic en la fila de un grupo (no en la flecha de expandir) = marcar/desmarcar
            if row in node_hash and "indicator" not in pv.identify_element(event.x, event.y):
                toggle([row])

        def on_space(_):
            sel = pv.selection()
            nodes = {s if s in node_hash else pv.parent(s) for s in sel}
            toggle([n for n in nodes if n in node_hash])
            return "break"

        pv.bind("<ButtonRelease-1>", on_click)
        pv.bind("<space>", on_space)

        bf = ttk.Frame(dlg, padding=8); bf.pack(fill="x")
        ttk.Label(bf, textvariable=summary).pack(side="left")
        ttk.Button(bf, text="Cancelar", command=dlg.destroy).pack(side="right")
        clean_ok = ttk.Button(bf, text="Limpiar", command=lambda: do_clean())
        clean_ok.pack(side="right", padx=6)
        cb.bind("<<ComboboxSelected>>", refresh); refresh()

        def do_clean():
            selected = [g for g in groups if g["hash"] not in skipped]
            if not selected:
                return
            perm = permanent.get()
            if perm:
                msg = (f"Se van a BORRAR DEFINITIVAMENTE {state['plan_n']} archivos.\n"
                       "Esta accion no se puede deshacer.\n\n¿Continuar?")
            else:
                msg = (f"Se van a mover {state['plan_n']} archivos a\n"
                       f"{os.path.join(folder, QUARANTINE_DIR)}\n\nPodras restaurarlos despues. ¿Continuar?")
            if not messagebox.askyesno("Confirmar limpieza", msg, icon="warning", parent=dlg):
                return
            cfg_now = load_config(); cfg_now["keep"] = keep.get(); save_config(cfg_now)
            dlg.destroy()
            bar.start(10); run_btn.state(["disabled"]); clean_btn.state(["disabled"])

            def work():
                try:
                    res = clean_duplicates(selected, folder, keep.get(), perm, _progress)
                    root.after(0, _clean_done, res)
                except Exception as e:  # noqa: BLE001
                    root.after(0, messagebox.showerror, "Error", str(e))
                finally:
                    root.after(0, lambda: (bar.stop(), run_btn.state(["!disabled"])))
            threading.Thread(target=work, daemon=True).start()

    def _clean_done(res):
        msg = f"Eliminados: {res['removed']} archivos\nEspacio liberado: {human(res['freed'])}"
        if res["quarantine"]:
            msg += f"\n\nMovidos a:\n{res['quarantine']}\n\nUsa 'Restaurar...' para deshacer."
        if res["errors"]:
            msg += f"\n\n{len(res['errors'])} archivos se saltaron (ver consola)."
            for e in res["errors"]:
                _warn(e)
        messagebox.showinfo("Limpieza terminada", msg)
        state["data"] = None
        _run()   # volver a buscar para mostrar el estado actual

    def _restore():
        base = os.path.join(folder_a.get().strip(), QUARANTINE_DIR)
        d = filedialog.askdirectory(title="Elige la carpeta de cuarentena (fecha_hora) a restaurar",
                                    initialdir=base if os.path.isdir(base) else os.path.expanduser("~"))
        if not d:
            return
        if not os.path.isfile(os.path.join(d, LOG_NAME)):
            messagebox.showerror("Restaurar", f"Esa carpeta no tiene {LOG_NAME}. "
                                              "Elige una subcarpeta con fecha y hora.")
            return
        try:
            res = restore_quarantine(d)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Restaurar", str(e)); return
        msg = f"Restaurados: {res['restored']} archivos."
        if res["errors"]:
            msg += f"\n{len(res['errors'])} no se pudieron restaurar (ver consola)."
            for e in res["errors"]:
                _warn(e)
        messagebox.showinfo("Restaurar", msg)

    def _export(kind):
        if state["data"] is None:
            messagebox.showinfo("Exportar", "Primero ejecuta una busqueda.")
            return
        path = filedialog.asksaveasfilename(defaultextension=f".{kind}",
                                            filetypes=[(kind.upper(), f"*.{kind}")])
        if path:
            export(state["mode"], state["data"], path if kind == "json" else None,
                   path if kind == "csv" else None)
            status.set(f"Guardado en {path}")

    def _open_selected():
        sel = tree.selection()
        if not sel:
            return
        p = tree.item(sel[0], "text")
        if not os.path.exists(p):
            return
        folder = os.path.dirname(p)
        if sys.platform.startswith("win"):
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{folder}"')
        else:
            os.system(f'xdg-open "{folder}" >/dev/null 2>&1 &')

    tree.bind("<Double-1>", lambda e: _open_selected())
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main_cli(sys.argv[1:]))
