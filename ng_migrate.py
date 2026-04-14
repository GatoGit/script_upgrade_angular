#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, json, os, re, subprocess, sys, time, zipfile, difflib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# ======== Config Snapshot / Paths ========
IGNORE_DIRS = {
    "node_modules", "dist", ".angular", ".git", ".idea", ".vscode",
    "coverage", "tmp", "temp", ".migrate_backups", ".migrate_reports"
}
SNAP_DIR   = Path(".migrate_backups")
REPORT_DIR = Path(".migrate_reports")
STATE_FILE = Path(".migrate_state.json")
REQUIRED_FILES = ["angular.json", "package.json"]
LAST_ERR = Path("last_build_error.log")

# Paquetes incompatibles a remover temporalmente al salto v14
TEMP_REMOVE = [
    "@mat-datetimepicker/core",
    "@mat-datetimepicker/moment",
]

# ======== Utils básicos ========
def sh(cmd: List[str], check=True) -> subprocess.CompletedProcess:
    print("» " + " ".join(cmd))
    return subprocess.run(cmd, text=True, capture_output=True, check=check)

def log(msg: str): print(msg, flush=True)

def ensure_project_root():
    for f in REQUIRED_FILES:
        if not Path(f).exists():
            sys.exit(f"❌ No se encontró {f}. Ejecuta el script en la raíz del proyecto Angular.")

def node_check():
    try:
        major = int(sh(["node", "-p", "process.versions.node.split('.')[0]"]).stdout.strip())
    except Exception:
        sys.exit("❌ Node no está en PATH.")
    if major < 20:
        sys.exit("❌ Se requiere Node >= 20.19 (recomendado 22.x).")

def detect_pm() -> str:
    if Path("pnpm-lock.yaml").exists(): return "pnpm"
    if Path("yarn.lock").exists(): return "yarn"
    return "npm"

def has_material() -> bool:
    try:
        pkg = json.loads(Path("package.json").read_text(encoding="utf-8"))
        deps = {**pkg.get("dependencies",{}), **pkg.get("devDependencies",{})}
        return "@angular/material" in deps
    except Exception:
        return False

def is_nx() -> bool:
    return Path("nx.json").exists()

# ======== npm sin depender del PATH (usa node + npm-cli.js) ========
def _node_exec_path() -> Path:
    p = sh(["node", "-p", "process.execPath"]).stdout.strip()
    return Path(p)

def _npm_cli_js_path() -> Path:
    node_exe = _node_exec_path()
    candidates = [
        # Windows: junto al ejecutable de Node
        node_exe.parent / "node_modules" / "npm" / "bin" / "npm-cli.js",
        # Linux/Mac (nvm): lib/node_modules junto al bin de Node
        node_exe.parent.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js",
        # Linux sistema: /usr/local/lib
        Path("/usr/local/lib/node_modules/npm/bin/npm-cli.js"),
        # Linux sistema alternativo: /usr/lib
        Path("/usr/lib/node_modules/npm/bin/npm-cli.js"),
    ]
    # Windows: APPDATA\npm
    appdata = os.getenv("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "npm" / "node_modules" / "npm" / "bin" / "npm-cli.js")
    for c in candidates:
        if c.exists():
            return c
    raise SystemExit("❌ No se encontró npm-cli.js. Reinstala Node con npm incluido.")

def npm_run(*args: str) -> subprocess.CompletedProcess:
    npm_cli = _npm_cli_js_path()
    cmd = ["node", str(npm_cli), *args]
    return sh(cmd)

# ======== Gestor de paquetes ========
def pm_install(pm: str):
    if pm == "pnpm": sh(["pnpm","install"])
    elif pm == "yarn": sh(["yarn","install"])
    else: npm_run("install")

def pm_dedupe(pm: str):
    try:
        if pm == "pnpm": sh(["pnpm","dedupe"])
        elif pm == "yarn": log("ℹ️ yarn no tiene dedupe estándar (omitiendo).")
        else: npm_run("dedupe")
    except subprocess.CalledProcessError as e:
        log(f"⚠️ dedupe: {e.stderr.strip()[:200]} (continuando)")

def pm_add_dev(pm: str, pkg_with_ver: str):
    if pm == "pnpm": sh(["pnpm","add","-D",pkg_with_ver])
    elif pm == "yarn": sh(["yarn","add","-D",pkg_with_ver])
    else: npm_run("install","-D",pkg_with_ver)

# ======== Ejecutores (sin npx) ========
def _ng_cli_installed_major() -> Optional[int]:
    """Devuelve el major del @angular/cli instalado en node_modules, o None."""
    ng_pkg = Path("node_modules") / "@angular" / "cli" / "package.json"
    if ng_pkg.exists():
        try:
            v = json.loads(ng_pkg.read_text(encoding="utf-8")).get("version", "")
            return int(v.split(".")[0])
        except Exception:
            pass
    return None

def run_ng(pm: str, cli_ver: int, *args: str) -> subprocess.CompletedProcess:
    if _ng_cli_installed_major() != cli_ver:
        pm_add_dev(pm, f"@angular/cli@{cli_ver}")
    ng_bin = ["node", str(Path("node_modules") / "@angular" / "cli" / "bin" / "ng.js")]
    return sh(ng_bin + list(args))

def run_nx(pm: str, *args: str) -> subprocess.CompletedProcess:
    if not Path("node_modules/nx/bin/nx.js").exists():
        pm_add_dev(pm, "nx")
    nx_bin = ["node", str(Path("node_modules") / "nx" / "bin" / "nx.js")]
    return sh(nx_bin + list(args))

def try_build_cli(pm: str, cli_ver: int, project: Optional[str], prod: bool) -> Tuple[bool,str]:
    args = ["build"] + ([project] if project else [])
    if prod: args += ["--configuration=production"]
    try:
        p = run_ng(pm, cli_ver, *args)
        return True, p.stdout + "\n" + p.stderr
    except subprocess.CalledProcessError as e:
        return False, (e.stdout or "") + "\n" + (e.stderr or "")

def try_build_nx(pm: str, project: str, prod: bool) -> Tuple[bool,str]:
    args = ["build", project]
    if prod: args += ["--configuration=production"]
    try:
        p = run_nx(pm, *args)
        return True, p.stdout + "\n" + p.stderr
    except subprocess.CalledProcessError as e:
        return False, (e.stdout or "") + "\n" + (e.stderr or "")

def try_build_server_cli(pm: str, cli_ver: int, project: str) -> Tuple[bool,str]:
    try:
        p = run_ng(pm, cli_ver, "run", f"{project}:server")
        return True, p.stdout + "\n" + p.stderr
    except subprocess.CalledProcessError as e:
        return False, (e.stdout or "") + "\n" + (e.stderr or "")

def try_build_server_nx(pm: str, project: str) -> Tuple[bool,str]:
    try:
        p = run_nx(pm, "run", f"{project}:server")
        return True, p.stdout + "\n" + p.stderr
    except subprocess.CalledProcessError as e:
        return False, (e.stdout or "") + "\n" + (e.stderr or "")

# ======== Workspace / projects ========
def read_workspace() -> Dict[str,Any]:
    return json.loads(Path("angular.json").read_text(encoding="utf-8"))

def list_projects() -> List[str]:
    ws = read_workspace()
    prj = ws.get("projects", {}) or {}
    names = list(prj.keys())
    apps=[]
    for name in names:
        p = prj[name]
        targets = p.get("targets") or p.get("architect") or {}
        if "build" in targets:
            apps.append(name)
    if not apps:
        dp = ws.get("defaultProject")
        return [dp] if dp else []
    return apps

def project_has_server_target(project: str) -> bool:
    ws = read_workspace()
    p = ws.get("projects", {}).get(project, {})
    targets = p.get("targets") or p.get("architect") or {}
    return "server" in targets

# ======== Snapshots & Reporte ========
def ensure_dirs():
    SNAP_DIR.mkdir(exist_ok=True)
    REPORT_DIR.mkdir(exist_ok=True)

def list_files_for_snapshot(root: Path, mode: str):
    code_exts = {
        '.ts','.tsx','.js','.mjs','.cjs','.json','.html','.scss','.sass','.css',
        '.md','.yaml','.yml','.env','.txt','.xml'
    }
    binary_block = {
        '.mp4','.mov','.avi','.mkv','.zip','.rar','.7z','.iso',
        '.psd','.psb','.ai','.eps','.pdf','.xlsx','.xls','.pptx','.ppt',
        '.apk','.exe','.dmg'
    }
    keep_names = {
        "angular.json","package.json","package-lock.json","pnpm-lock.yaml","yarn.lock",
        "nx.json","tsconfig.json","tsconfig.base.json",".browserslistrc"
    }
    for p in root.rglob("*"):
        if p.is_dir():
            if any(part in IGNORE_DIRS for part in p.parts): continue
        else:
            if any(part in IGNORE_DIRS for part in p.parts): continue
            if mode == "lite":
                suff = p.suffix.lower()
                if p.name in keep_names or (suff in code_exts and suff not in binary_block):
                    yield p
                continue
            yield p

def make_snapshot(label: str, mode: str) -> Path:
    ensure_dirs()
    if mode == "off":
        log(f"⏭️  Snapshot omitido ({label}) por snapshot=off")
        return Path(f"SKIPPED_{label}.zip")
    ts = time.strftime("%Y%m%d-%H%M%S")
    zpath = SNAP_DIR / f"{ts}_{label}.zip"
    files = list(list_files_for_snapshot(Path("."), mode))
    try:
        zr = zpath.resolve()
        files = [p for p in files if p.resolve() != zr]
    except Exception:
        pass
    log(f"💾 Snapshot: {zpath}")
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as z:
        for f in files:
            z.write(f, arcname=str(f))
    state = load_state()
    state.setdefault("snapshots", []).append(str(zpath))
    save_state(state)
    return zpath

def restore_snapshot(target: str):
    ensure_dirs()
    if target == "latest":
        snaps = sorted(SNAP_DIR.glob("*.zip"))
        if not snaps: sys.exit("No hay snapshots para restaurar.")
        zpath = snaps[-1]
    else:
        zpath = SNAP_DIR / target if not target.endswith(".zip") else Path(target)
        if not zpath.exists(): sys.exit(f"Snapshot no existe: {zpath}")
    log(f"↩️  Restaurando snapshot: {zpath}")
    with zipfile.ZipFile(zpath, "r") as z:
        z.extractall(Path("."))
    log("✅ Restaurado.")

def load_state() -> Dict[str,Any]:
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception: return {}
    return {}

def save_state(data: Dict[str,Any]): STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

class Report:
    def __init__(self):
        self.records = []
        self.start_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        ensure_dirs()
    def add(self, rec: Dict[str,Any]): self.records.append(rec)
    def write_html(self) -> Path:
        ts = time.strftime("%Y%m%d-%H%M%S")
        out = REPORT_DIR / f"migration_report_{ts}.html"
        css = """
        body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:24px}
        h1{margin-bottom:0} small{color:#666}
        pre{background:#0b1020;color:#e5ecff;padding:12px;overflow:auto;border-radius:8px}
        .ok{color:#0a7a2d}.bad{color:#b00020}
        .card{border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin:12px 0}
        """
        html = [f"<html><head><meta charset='utf-8'><style>{css}</style><title>Angular 13→20 Reporte</title></head><body>"]
        html += [f"<h1>Reporte de migración Angular 13→20</h1><small>Inicio: {self.start_ts}</small>"]
        for rec in self.records:
            html += [f"<div class='card'><h2>{rec['title']}</h2>"]
            html += [f"<p><b>Resultado:</b> {'<span class=ok>OK</span>' if rec['success'] else '<span class=bad>FALLÓ</span>'}</p>"]
            if rec.get("details"):
                html += ["<details><summary><b>Detalles</b></summary><pre>"]
                html += [rec["details"]]
                html += ["</pre></details>"]
            html += ["</div>"]
        html += ["</body></html>"]
        out.write_text("\n".join(html), encoding="utf-8")
        return out

def diff_text(a: str, b: str, fromfile="before/package.json", tofile="after/package.json") -> str:
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), fromfile, tofile))

# ======== Pin de TypeScript por versión ========
def pin_typescript_for(pm: str, angular_major: int):
    ts_map = {
        14: "~4.6.4",
        15: "~4.8.4",
        16: "~4.9.5",
        17: "~5.2.2",
        18: "~5.4.5",
        19: "~5.5.4",
        20: "~5.8.2",
    }
    ver = ts_map.get(angular_major)
    if not ver: return
    pkg_path = Path("package.json")
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    if "devDependencies" not in pkg:
        pkg["devDependencies"] = {}
    if pkg["devDependencies"].get("typescript") != ver:
        pkg["devDependencies"]["typescript"] = ver
        pkg_path.write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
        pm_install(pm)

# ======== Alinear CLI y build-angular al major del salto ========
def align_cli_and_builder(pm: str, angular_major: int):
    pkg_path = Path("package.json")
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    dev = pkg.get("devDependencies") or {}
    dep = pkg.get("dependencies") or {}
    desired = f"^{angular_major}.0.0"

    if dev.get("@angular/cli") != desired:
        dev["@angular/cli"] = desired

    # @angular-devkit/build-angular (legacy, sigue funcionando como shim hasta v20)
    if dep.get("@angular-devkit/build-angular"):
        dep.pop("@angular-devkit/build-angular", None)
    if dev.get("@angular-devkit/build-angular") != desired:
        dev["@angular-devkit/build-angular"] = desired

    # @angular/build — nuevo paquete desde v17; actualizar si ya está presente
    if angular_major >= 17:
        if dep.get("@angular/build"):
            dep.pop("@angular/build", None)
        if dev.get("@angular/build") is not None and dev.get("@angular/build") != desired:
            dev["@angular/build"] = desired

    pkg["devDependencies"] = dev
    pkg["dependencies"] = dep
    pkg_path.write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
    pm_install(pm)

def _installed_packages() -> Dict[str, str]:
    try:
        pkg = json.loads(Path("package.json").read_text(encoding="utf-8"))
        return {**pkg.get("dependencies",{}), **pkg.get("devDependencies",{})}
    except Exception:
        return {}

def temp_remove_incompatible(pm: str):
    deps = _installed_packages()
    to_remove = [p for p in TEMP_REMOVE if p in deps]
    if not to_remove: return
    try:
        if pm == "pnpm": sh(["pnpm","remove"] + to_remove)
        elif pm == "yarn": sh(["yarn","remove"] + to_remove)
        else: npm_run("remove", *to_remove)
        log(f"🧹 Removidos temporalmente: {', '.join(to_remove)}")
    except subprocess.CalledProcessError as e:
        log(f"⚠️ No se pudieron remover algunos paquetes: {e.stderr[:200]}")

# ======== Autofix de MaterialModule (reescribe/crea) ========
def ensure_material_module_autofix() -> int:
    pkg = {}
    try:
        pkg = json.loads(Path("package.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    use_moment_adapter = "@angular/material-moment-adapter" in deps

    adapter_import = (
        "import { MatMomentDateModule } from '@angular/material-moment-adapter';"
        if use_moment_adapter else
        "import { MatNativeDateModule } from '@angular/material/core';"
    )
    adapter_token = "MatMomentDateModule" if use_moment_adapter else "MatNativeDateModule"

    template = f"""/* AUTO-GENERADO por migración: MaterialModule “safe” para Angular 14+ */
import {{ NgModule }} from '@angular/core';
import {{ CommonModule }} from '@angular/common';

import {{ MatAutocompleteModule }} from '@angular/material/autocomplete';
import {{ MatBadgeModule }} from '@angular/material/badge';
import {{ MatBottomSheetModule }} from '@angular/material/bottom-sheet';
import {{ MatButtonModule }} from '@angular/material/button';
import {{ MatButtonToggleModule }} from '@angular/material/button-toggle';
import {{ MatCardModule }} from '@angular/material/card';
import {{ MatCheckboxModule }} from '@angular/material/checkbox';
import {{ MatChipsModule }} from '@angular/material/chips';
import {{ MatDatepickerModule }} from '@angular/material/datepicker';
import {{ MatDialogModule }} from '@angular/material/dialog';
import {{ MatDividerModule }} from '@angular/material/divider';
import {{ MatExpansionModule }} from '@angular/material/expansion';
import {{ MatFormFieldModule }} from '@angular/material/form-field';
import {{ MatIconModule }} from '@angular/material/icon';
import {{ MatInputModule }} from '@angular/material/input';
import {{ MatListModule }} from '@angular/material/list';
import {{ MatMenuModule }} from '@angular/material/menu';
import {{ MatPaginatorModule }} from '@angular/material/paginator';
import {{ MatProgressBarModule }} from '@angular/material/progress-bar';
import {{ MatProgressSpinnerModule }} from '@angular/material/progress-spinner';
import {{ MatRadioModule }} from '@angular/material/radio';
import {{ MatSelectModule }} from '@angular/material/select';
import {{ MatSidenavModule }} from '@angular/material/sidenav';
import {{ MatSlideToggleModule }} from '@angular/material/slide-toggle';
import {{ MatSliderModule }} from '@angular/material/slider';
import {{ MatSnackBarModule }} from '@angular/material/snack-bar';
import {{ MatSortModule }} from '@angular/material/sort';
import {{ MatTableModule }} from '@angular/material/table';
import {{ MatTabsModule }} from '@angular/material/tabs';
import {{ MatToolbarModule }} from '@angular/material/toolbar';
import {{ MatTooltipModule }} from '@angular/material/tooltip';
import {{ MatTreeModule }} from '@angular/material/tree';
{adapter_import}

const EXPORTED = [
  MatAutocompleteModule, MatBadgeModule, MatBottomSheetModule,
  MatButtonModule, MatButtonToggleModule, MatCardModule, MatCheckboxModule,
  MatChipsModule, MatDatepickerModule, MatDialogModule, MatDividerModule,
  MatExpansionModule, MatFormFieldModule, MatIconModule, MatInputModule,
  MatListModule, MatMenuModule, MatPaginatorModule, MatProgressBarModule,
  MatProgressSpinnerModule, MatRadioModule, MatSelectModule, MatSidenavModule,
  MatSlideToggleModule, MatSliderModule, MatSnackBarModule, MatSortModule,
  MatTableModule, MatTabsModule, MatToolbarModule, MatTooltipModule,
  MatTreeModule, {adapter_token}
];

@NgModule({{
  imports: [CommonModule, ...EXPORTED],
  exports: EXPORTED
}})
export class MaterialModule {{}}
"""
    changed = 0
    candidates = list(Path(".").rglob("material.module.ts"))
    if not candidates:
        default_path = Path("src/app/material.module.ts")
        default_path.parent.mkdir(parents=True, exist_ok=True)
        default_path.write_text(template, encoding="utf-8")
        return 1

    for p in candidates:
        p.write_text(template, encoding="utf-8")
        changed += 1
    return changed

def update_existing_material_modules() -> int:
    """Normaliza material.module.ts solo si ya existe en el proyecto. No crea archivos nuevos."""
    candidates = list(Path(".").rglob("material.module.ts"))
    if not candidates:
        return 0
    return ensure_material_module_autofix()

# ======== Helpers de análisis de código ========
def ts_read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")

def find_component_class_from_ts(ts_path: Path) -> Optional[str]:
    m = re.search(r"export\s+class\s+([A-Za-z0-9_]+)\s*", ts_read(ts_path))
    return m.group(1) if m else None

def find_selector_map() -> Dict[str, Tuple[Path, str]]:
    selmap = {}
    for ts in Path(".").rglob("*.component.ts"):
        txt = ts_read(ts)
        for m in re.finditer(r"selector\s*:\s*['\"]([^'\"]+)['\"]", txt):
            comp = find_component_class_from_ts(ts)
            if comp:
                selmap[m.group(1)] = (ts, comp)
    return selmap

def find_module_declaring_class(class_name: str) -> Optional[Tuple[Path, str]]:
    for mod in Path(".").rglob("*.module.ts"):
        txt = ts_read(mod)
        if re.search(rf"declarations\s*:\s*\[[^\]]*?\b{re.escape(class_name)}\b", txt, re.S):
            m = re.search(r"@NgModule\s*\([\s\S]*?\)\s*export\s+class\s+([A-Za-z0-9_]+)", txt)
            if m:
                return mod, m.group(1)
    return None

def find_consumer_module_for_component(ts_path: Path) -> Optional[Path]:
    comp = find_component_class_from_ts(ts_path)
    if not comp: return None
    for mod in Path(".").rglob("*.module.ts"):
        if re.search(rf"declarations\s*:\s*\[[^\]]*?\b{re.escape(comp)}\b", ts_read(mod), re.S):
            return mod
    return None

def ensure_import_in_module(mod_path: Path, import_cls: str, import_from: str) -> bool:
    txt = ts_read(mod_path)
    changed = False
    if f"import {{ {import_cls} }}" not in txt:
        txt = f"import {{ {import_cls} }} from '{import_from}';\n" + txt
        changed = True
    def add_to_imports(block: str) -> str:
        if re.search(rf"imports\s*:\s*\[([^\]]*)\]", block, re.S):
            def repl(m):
                inner = m.group(1)
                if re.search(rf"\b{re.escape(import_cls)}\b", inner): return m.group(0)
                return f"imports: [{inner}, {import_cls}]"
            return re.sub(r"imports\s*:\s*\[([^\]]*)\]", repl, block, flags=re.S)
        else:
            return re.sub(r"@NgModule\s*\(\s*\{", f"@NgModule({{\n  imports: [{import_cls}],", block)
    new_txt = re.sub(r"@NgModule\s*\([\s\S]*?\)\s*export\s+class\s+[A-Za-z0-9_]+\s*\{[^}]*\}",
                     lambda m: add_to_imports(m.group(0)), txt, count=1, flags=re.S)
    if new_txt != txt:
        txt = new_txt; changed = True
    if changed:
        mod_path.write_text(txt, encoding="utf-8")
    return changed

def ensure_schema_in_module(mod_path: Path, schema: str) -> bool:
    txt = ts_read(mod_path)
    changed = False
    # Detecta si el schema ya está importado en cualquier forma:
    # import { Schema } o import { A, Schema, B } from '@angular/core'
    already_imported = bool(re.search(
        rf"import\s*\{{[^}}]*\b{re.escape(schema)}\b[^}}]*\}}\s*from\s*'@angular/core'", txt
    ))
    if not already_imported:
        if "from '@angular/core'" in txt:
            txt = txt.replace("from '@angular/core';", f"from '@angular/core';\nimport {{ {schema} }} from '@angular/core';")
        else:
            txt = f"import {{ {schema} }} from '@angular/core';\n" + txt
        changed = True
    if not re.search(r"schemas\s*:", txt):
        txt = re.sub(r"@NgModule\s*\(\s*\{", f"@NgModule({{\n  schemas: [{schema}],", txt, count=1)
        changed = True
    else:
        def repl(m):
            inner = m.group(1)
            if re.search(rf"\b{re.escape(schema)}\b", inner): return m.group(0)
            return f"schemas: [{inner}, {schema}]"
        txt2 = re.sub(r"schemas\s*:\s*\[([^\]]*)\]", repl, txt)
        if txt2 != txt:
            txt = txt2; changed = True
    if changed:
        mod_path.write_text(txt, encoding="utf-8")
    return changed

def find_material_module_path() -> Optional[Path]:
    candidates = list(Path(".").rglob("material.module.ts"))
    return candidates[0] if candidates else None

def ensure_import_material_module(consumer_mod: Path) -> bool:
    mm = find_material_module_path()
    if not mm:
        # crearlo y reintentar
        ensure_material_module_autofix()
        mm = find_material_module_path()
        if not mm: return False
    rel = os.path.relpath(str(mm).replace("\\", "/").removesuffix(".ts"),
                          start=str(consumer_mod.parent).replace("\\", "/"))
    if not rel.startswith("."): rel = "./" + rel
    return ensure_import_in_module(consumer_mod, "MaterialModule", rel)

# ======== Autofix a partir del log de build ========
UNKNOWN_EL_RE = re.compile(r"Error:\s+(.+?\.component\.html):\d+:\d+\s+-\s+error NG8001:\s+'([^']+)'\s+is not a known element", re.I)
UNKNOWN_PROP_RE = re.compile(r"Error:\s+(.+?\.component\.html):\d+:\d+\s+-\s+error NG8002:\s+Can't bind to '([^']+)'\s+since it isn't a known property of '([^']+)'", re.I)

def fix_unknown_element(tag: str, tpl_path: Path, selector_map: Dict[str, Tuple[Path,str]]) -> bool:
    consumer_ts = Path(str(tpl_path).replace(".component.html", ".component.ts"))
    consumer_mod = find_consumer_module_for_component(consumer_ts)
    if not consumer_mod: return False

    # 1) Casos Angular Material (mat-*)
    if tag.startswith("mat-"):
        changed = ensure_import_material_module(consumer_mod)
        # Plan B: importar directamente el módulo específico si es botón toggle
        if tag in ("mat-button-toggle", "mat-button-toggle-group"):
            changed |= ensure_import_in_module(consumer_mod, "MatButtonToggleModule", "@angular/material/button-toggle")
        if tag in ("mat-table",):
            changed |= ensure_import_in_module(consumer_mod, "MatTableModule", "@angular/material/table")
        if changed:
            log(f"✅ Material importado en {consumer_mod} para '{tag}'")
        return changed

    # 2) Componente propio: importar el módulo que lo declara
    if tag in selector_map:
        comp_ts, comp_class = selector_map[tag]
        decl = find_module_declaring_class(comp_class)
        if not decl: return False
        decl_mod_path, decl_mod_class = decl
        rel = os.path.relpath(str(decl_mod_path).replace("\\", "/").removesuffix(".ts"),
                              start=str(consumer_mod.parent).replace("\\","/"))
        if not rel.startswith("."): rel = "./" + rel
        changed = ensure_import_in_module(consumer_mod, decl_mod_class, rel.replace("\\","/"))
        if changed:
            log(f"✅ Importado {decl_mod_class} en {consumer_mod} (selector '{tag}')")
        return changed

    # 3) Web Component probable
    if "-" in tag:
        changed = ensure_schema_in_module(consumer_mod, "CUSTOM_ELEMENTS_SCHEMA")
        if changed:
            log(f"✅ Añadido CUSTOM_ELEMENTS_SCHEMA en {consumer_mod} para '{tag}'")
        return changed

    return False

def fix_unknown_property(prop: str, host: str, tpl_path: Path) -> bool:
    consumer_ts = Path(str(tpl_path).replace(".component.html", ".component.ts"))
    consumer_mod = find_consumer_module_for_component(consumer_ts)
    if not consumer_mod: return False
    added = False

    html = ts_read(tpl_path)
    if re.search(r"\bmat-table\b", html) or (host.lower()=="table" and prop=="dataSource"):
        added |= ensure_import_in_module(consumer_mod, "MatTableModule", "@angular/material/table")
    if re.search(r"\bmat-paginator\b", html):
        added |= ensure_import_in_module(consumer_mod, "MatPaginatorModule", "@angular/material/paginator")
    if re.search(r"\bmatSort\b|\bmat-sort-header\b", html):
        added |= ensure_import_in_module(consumer_mod, "MatSortModule", "@angular/material/sort")
    if added:
        log(f"✅ Añadidos módulos Material de tabla en {consumer_mod}")
    return added

def smart_autofix_from_log(pm: str, log_path: Path) -> int:
    if not log_path.exists(): return 0
    txt = log_path.read_text(encoding="utf-8", errors="ignore")
    fixes = 0
    selector_map = find_selector_map()

    for m in UNKNOWN_EL_RE.finditer(txt):
        tpl = Path(m.group(1)); tag = m.group(2)
        if tpl.exists():
            if fix_unknown_element(tag, tpl, selector_map):
                fixes += 1

    for m in UNKNOWN_PROP_RE.finditer(txt):
        tpl = Path(m.group(1)); prop = m.group(2); host = m.group(3)
        if tpl.exists():
            if fix_unknown_property(prop, host, tpl):
                fixes += 1

    if fixes > 0:
        pm_install(pm)
    return fixes

# ======== Terceros ========
def update_third_party(pm: str):
    log("🔄 Actualizando librerías de terceros (minor/patch)…")
    try:
        if pm == "pnpm": sh(["pnpm","update"])
        elif pm == "yarn": sh(["yarn","upgrade"])
        else: npm_run("update")
    except subprocess.CalledProcessError as e:
        log(f"⚠️ update avisó: {e.stderr[:200]}")
    if Path("package.json").exists():
        pkg = json.loads(Path("package.json").read_text(encoding="utf-8"))
        changed = False
        for sect in ("dependencies","devDependencies"):
            deps = pkg.get(sect,{})
            if "rxjs" in deps and deps["rxjs"] != "^7.8.0":
                deps["rxjs"] = "^7.8.0"; changed = True
            if "zone.js" in deps and deps["zone.js"] != "^0.14.0":
                deps["zone.js"] = "^0.14.0"; changed = True
        if changed:
            Path("package.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
            pm_install(pm)
    pm_dedupe(pm)

# ======== Migración principal ========
def migrate(snapshot_mode: str, standalone: bool, control_flow: bool, material_mdc: bool,
            material_m3: bool, check_ssr: bool):
    ensure_project_root()
    node_check()
    pm = detect_pm()
    mat = has_material()
    nx = is_nx()
    projects = list_projects()
    if not projects:
        sys.exit("❌ No encontré apps en angular.json. Revisa el workspace.")
    ws = read_workspace()
    default_project = ws.get("defaultProject")

    log(f"🚀 Migración Angular 13 → 20 (PM={pm}, Material={mat}, Nx={nx})")
    log(f"🧩 Proyectos encontrados: {', '.join(projects)}")
    if default_project: log(f"⭐ Proyecto por defecto: {default_project}")

    report = Report()

    for v in range(14, 21):
        make_snapshot(f"pre_v{v}", snapshot_mode)

        # Pin TS apropiado y fixes previos al salto
        pin_typescript_for(pm, v)
        if v == 14:
            temp_remove_incompatible(pm)
        align_cli_and_builder(pm, v)

        # 🔧 Normaliza MaterialModule(s) solo si el proyecto usa Material y ya tiene el archivo
        if mat:
            fixed_mats = update_existing_material_modules()
            if fixed_mats:
                log(f"🔧 MaterialModule(s) normalizados: {fixed_mats}")

        pkg_before = Path("package.json").read_text(encoding="utf-8")

        # Core/CLI
        try:
            run_ng(pm, v, "update", f"@angular/core@{v}", f"@angular/cli@{v}", "--allow-dirty", "--force")
        except subprocess.CalledProcessError as e:
            LAST_ERR.write_text((e.stdout or "") + "\n" + (e.stderr or ""), encoding="utf-8")
            report.add({"title": f"ng update core/cli v{v}", "success": False, "details": (e.stderr or "")[-4000:]})
            outpath = report.write_html()
            sys.exit(f"❌ ng update v{v} falló. Reporte: {outpath}")

        # Material
        if mat:
            try:
                run_ng(pm, v, "update", f"@angular/material@{v}", "--allow-dirty", "--force")
            except subprocess.CalledProcessError as e:
                log(f"⚠️ Material v{v}: {(e.stderr or '').strip()[:200]} (continuando)")

        # Builder nuevo desde v18
        if v >= 18:
            aj = Path("angular.json").read_text(encoding="utf-8", errors="ignore")
            if '"@angular-devkit/build-angular:application"' not in aj:
                try:
                    run_ng(pm, v, "update", "@angular/cli", "--migrate-only", "--name", "use-application-builder", "--allow-dirty", "--force")
                except subprocess.CalledProcessError:
                    log("⚠️ use-application-builder no se pudo aplicar automáticamente (continuando)")

        pm_install(pm); pm_dedupe(pm)

        # Build (con reintento y autofix)
        all_ok = True
        outputs=[]
        for prj in projects:
            if nx:
                ok, out = try_build_nx(pm, prj, prod=True)
            else:
                ok, out = try_build_cli(pm, v, prj, prod=True)
            outputs.append(out[-4000:])
            all_ok = all_ok and ok

        if not all_ok:
            LAST_ERR.write_text("\n\n".join(outputs), encoding="utf-8")
            applied = smart_autofix_from_log(pm, LAST_ERR)
            if applied > 0:
                log(f"🛠️  Autofixes aplicados: {applied}. Reintentando build v{v}…")
                all_ok = True
                outputs=[]
                for prj in projects:
                    if nx:
                        ok, out = try_build_nx(pm, prj, prod=True)
                    else:
                        ok, out = try_build_cli(pm, v, prj, prod=True)
                    outputs.append(out[-4000:])
                    all_ok = all_ok and ok

        if not all_ok:
            LAST_ERR.write_text("\n\n".join(outputs), encoding="utf-8")
            diff = diff_text(pkg_before, Path("package.json").read_text(encoding="utf-8"))
            report.add({"title": f"Build v{v}", "success": False, "details": (diff + "\n\n" + ("\n\n".join(outputs)))[-6000:]})
            outpath = report.write_html()
            sys.exit(f"❌ Build falló en v{v}. Reporte: {outpath}")

        make_snapshot(f"post_v{v}", snapshot_mode)
        diff = diff_text(pkg_before, Path("package.json").read_text(encoding="utf-8"))
        report.add({"title": f"Salto v{v}", "success": True, "details": diff if diff.strip() else "Sin cambios relevantes en package.json"})

    # Codemods opcionales (ya en v20)
    if control_flow:
        try: run_ng(pm, 20, "generate", "@angular/core:control-flow")
        except subprocess.CalledProcessError as e: log(f"⚠️ control-flow: {(e.stderr or '').strip()[:200]}")
    if standalone:
        for mode in ("convert-to-standalone","remove-ng-modules","bootstrap"):
            try: run_ng(pm, 20, "generate", "@angular/core:standalone", f"--mode={mode}")
            except subprocess.CalledProcessError as e: log(f"⚠️ standalone ({mode}): {(e.stderr or '').strip()[:200]}")
    if has_material() and material_mdc:
        try: run_ng(pm, 20, "generate", "@angular/material:mdc-migration")
        except subprocess.CalledProcessError as e: log(f"⚠️ mdc-migration: {(e.stderr or '').strip()[:200]}")
    if has_material() and material_m3:
        try: run_ng(pm, 20, "generate", "@angular/material:m3-theme")
        except subprocess.CalledProcessError as e: log(f"⚠️ m3-theme: {(e.stderr or '').strip()[:200]}")

    # Terceros + lint
    update_third_party(pm)
    try: run_ng(pm, 20, "lint", "--fix")
    except subprocess.CalledProcessError: log("ℹ️ Lint no configurado o falló (continuando).")

    # Build final
    final_ok = True
    outputs=[]
    for prj in projects:
        if nx: ok, out = try_build_nx(pm, prj, prod=True)
        else:  ok, out = try_build_cli(pm, 20, prj, prod=True)
        outputs.append(out[-2000:])
        final_ok = final_ok and ok

    make_snapshot("final_ok", snapshot_mode)
    if not final_ok:
        LAST_ERR.write_text("\n\n".join(outputs), encoding="utf-8")
        report.add({"title": "Build final", "success": False, "details": ("\n\n".join(outputs))[-6000:]})
        outpath = report.write_html()
        sys.exit(f"❌ Build final falló. Reporte: {outpath}")

    report.add({"title": "Completado", "success": True, "details": "Migración terminada y compilación OK."})
    outpath = report.write_html()
    log(f"\n✅ Migración completada a Angular 20. Reporte: {outpath}")
    log("   Backups en .migrate_backups/. Puedes crear tu repo Git limpio ahora.")

# ======== CLI ========
def main():
    ap = argparse.ArgumentParser(description="Angular 13→20 SIN npx, snapshots, reporte HTML, CLI/Nx y fixes automáticos (Material + módulos desconocidos).")
    ap.add_argument("--snapshot", choices=["full","lite","off"], default="lite", help="Modo de snapshot (default: lite)")
    ap.add_argument("--standalone", action="store_true", help="Aplicar codemods Standalone")
    ap.add_argument("--control-flow", action="store_true", help="Convertir *ngIf/*ngFor/*ngSwitch a @if/@for/@switch")
    ap.add_argument("--material-mdc", action="store_true", help="Aplicar MDC migration (Material)")
    ap.add_argument("--material-m3", action="store_true", help="Generar base de tema Material 3")
    ap.add_argument("--check-ssr", action="store_true", help="Intentar compilar :server si existe (SSR)")
    ap.add_argument("--restore", type=str, help="Restaura snapshot: nombre.zip o 'latest'")
    args = ap.parse_args()

    if args.restore:
        restore_snapshot(args.restore); return
    migrate(args.snapshot, args.standalone, args.control_flow, args.material_mdc, args.material_m3, args.check_ssr)

if __name__ == "__main__":
    main()
