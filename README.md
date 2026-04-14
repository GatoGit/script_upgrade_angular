# ng_migrate — Migración automática de Angular

Script Python para migrar proyectos Angular paso a paso hasta la **versión 20**, sin usar `npx`. Detecta automáticamente la versión actual del proyecto y reanuda donde quedó si se interrumpe. Compatible con npm, pnpm y yarn, proyectos CLI y monorepos Nx.

---

## Características

- **Detección automática de versión** — lee la versión actual desde `package.json` y calcula los pasos necesarios
- **Migración paso a paso** con build de producción validado en cada salto
- **Reanuda automáticamente** — si se interrumpe en v17, al volver a ejecutar retoma desde v18
- **Output en tiempo real** — muestra la salida de installs y builds mientras corren, sin esperas silenciosas
- **Auto-detección** del gestor de paquetes (npm / pnpm / yarn) y de monorepos Nx
- **Pin de TypeScript** por versión de Angular — asigna la versión exacta compatible antes de cada salto
- **Snapshots ZIP** antes y después de cada versión — modos `full`, `lite` u `off`
- **Reporte HTML** con diff de `package.json` y salida de build por cada paso, con caracteres especiales correctamente escapados
- **Auto-fix inteligente** — parsea errores de build (NG8001 / NG8002) y parchea imports de módulos Angular automáticamente
- **Normalizador de MaterialModule** — reescribe/crea `material.module.ts` compatible con Angular 14+
- **Migraciones de librerías populares** — detecta NgRx, Angular Fire, Transloco, PrimeNG, ng-zorro, ng-bootstrap y otras, y ejecuta sus migraciones automáticamente
- **Limpieza de caché Angular** — borra `.angular/cache` antes de cada build para evitar falsos negativos
- **Soporte SSR** — con `--check-ssr` compila el target `:server` en cada paso si existe
- **Soporte `@angular/build`** — detecta y actualiza el nuevo paquete de build desde Angular 17
- **Codemods opcionales** (todos desactivados por defecto):
  - `--standalone` — convierte módulos a componentes Standalone
  - `--control-flow` — migra `*ngIf` / `*ngFor` / `*ngSwitch` a `@if` / `@for` / `@switch`
  - `--material-mdc` — aplica la migración MDC de Angular Material
  - `--material-m3` — genera la base del tema Material 3
- **Restauración de snapshot** — vuelve a cualquier punto guardado con un solo comando

---

## Requisitos

| Requisito | Versión |
|-----------|---------|
| Python    | 3.9+    |
| Node.js   | >= 20.19 (recomendado 22.x) |
| npm       | incluido con Node |

> pnpm y yarn se detectan automáticamente si existe su archivo de lock.

---

## Uso

Ejecuta el script **desde la raíz del proyecto Angular** (donde están `angular.json` y `package.json`):

```bash
python ng_migrate.py
```

### Todas las opciones

```
uso: ng_migrate.py [-h] [--snapshot {full,lite,off}] [--standalone]
                   [--control-flow] [--material-mdc] [--material-m3]
                   [--check-ssr] [--from-version N] [--restore RESTORE]

opciones:
  -h, --help                  muestra esta ayuda y sale
  --snapshot {full,lite,off}  modo de snapshot: full=todos los archivos,
                              lite=solo codigo, off=sin backups (default: lite)
  --standalone                aplica codemods Standalone al final
  --control-flow              convierte *ngIf/*ngFor/*ngSwitch a @if/@for/@switch
  --material-mdc              aplica migracion MDC (Angular Material)
  --material-m3               genera base de tema Material 3
  --check-ssr                 compila target :server en cada paso si existe (SSR)
  --from-version N            empieza desde la version N (14-20), saltando anteriores
  --restore RESTORE           restaura snapshot: nombre.zip o 'latest'
```

### Ejemplos

```bash
# Migracion basica — detecta version actual y arranca (snapshots lite, sin codemods)
python ng_migrate.py

# Migracion completa con codemods modernos y verificacion SSR
python ng_migrate.py --standalone --control-flow --material-mdc --check-ssr

# Sin snapshots (mas rapido, menos espacio en disco)
python ng_migrate.py --snapshot off

# Snapshots completos (incluye todos los archivos del proyecto)
python ng_migrate.py --snapshot full

# Retomar manualmente desde v17 (saltando v14, v15, v16)
python ng_migrate.py --from-version 17

# Volver al ultimo snapshot guardado
python ng_migrate.py --restore latest

# Volver a un snapshot especifico
python ng_migrate.py --restore .migrate_backups/20250910-120000_pre_v16.zip
```

---

## Cómo funciona

```
package.json (cualquier version >= 13)
    |
    +-- Detecta version actual (@angular/core)
    +-- Verifica ultimo salto exitoso (.migrate_state.json)
    |
    Para cada salto (version_actual+1 --> 20):
    |
    +-- snapshot pre_vN
    +-- Pin TypeScript compatible
    +-- Limpia cache Angular (.angular/cache)
    +-- ng update @angular/core@N @angular/cli@N
    +-- ng update @angular/material@N  (si aplica)
    +-- ng update de librerias detectadas (NgRx, Fire, etc.)
    +-- Migracion al application builder  (v18+)
    +-- npm install + dedupe
    +-- Build de produccion
    |       |
    |       +-- OK --> snapshot post_vN, guarda progreso
    |       +-- FALLA --> auto-fix (NG8001/NG8002) --> reintento
    |                         |
    |                         +-- OK --> continua
    |                         +-- FALLA --> reporte HTML + para
    |                                      (corregir a mano y re-ejecutar
    |                                       reanuda desde este paso)
    +-- Build SSR (:server) si --check-ssr
    |
    Codemods opcionales (standalone, control-flow, MDC, M3)
    Actualizacion de terceros (rxjs ^7.8, zone.js ^0.14)
    ng lint --fix
    Build final --> reporte HTML
```

### Librerías de terceros detectadas automáticamente

Si el proyecto tiene alguna de estas librerías, el script ejecuta `ng update` por cada una en cada salto:

| Librería | Paquete |
|----------|---------|
| NgRx | `@ngrx/store`, `@ngrx/effects`, `@ngrx/entity`, `@ngrx/router-store`, `@ngrx/component-store` |
| Angular Fire | `@angular/fire` |
| ngx-translate | `@ngx-translate/core` |
| Transloco | `@ngneat/transloco` |
| NG-ZORRO | `ng-zorro-antd` |
| PrimeNG | `primeng` |
| NG Bootstrap | `@ng-bootstrap/ng-bootstrap` |
| ngx-bootstrap | `ngx-bootstrap` |
| NGX Datatable | `@swimlane/ngx-datatable` |
| ngx-toastr | `ngx-toastr` |

### Mapa de versiones TypeScript

| Angular | TypeScript |
|---------|-----------|
| 14      | ~4.6.4    |
| 15      | ~4.8.4    |
| 16      | ~4.9.5    |
| 17      | ~5.2.2    |
| 18      | ~5.4.5    |
| 19      | ~5.5.4    |
| 20      | ~5.8.2    |

---

## Archivos generados

| Archivo / Carpeta       | Descripción |
|-------------------------|-------------|
| `.migrate_backups/`     | Snapshots ZIP antes/después de cada salto de versión |
| `.migrate_reports/`     | Reportes HTML con diffs y salida de build por paso |
| `.migrate_state.json`   | Estado interno: snapshots y versiones completadas (permite reanudar) |
| `last_build_error.log`  | Salida cruda del último build fallido — útil para depurar |

---

## Motor de auto-fix

Cuando un build falla, el script:

1. Parsea `last_build_error.log` buscando errores de plantillas Angular:
   - **NG8001** — elemento desconocido → importa el módulo correcto o añade `CUSTOM_ELEMENTS_SCHEMA`
   - **NG8002** — propiedad desconocida → importa los módulos de Material (tabla, paginador, sort) según corresponda
2. Aplica los fixes directamente en los archivos `*.module.ts` afectados
3. Limpia la caché Angular y reintenta el build
4. Si sigue fallando, escribe el reporte HTML y para con instrucciones claras

---

## Notas

- Funciona **sin `npx`** — resuelve `npm-cli.js` y el binario `ng` directamente a través de Node. Compatible con Windows, Linux y macOS.
- Elimina temporalmente `@mat-datetimepicker/core` y `@mat-datetimepicker/moment` durante el salto a v14 (son incompatibles en ese paso).
- Lee `angular.json` para detectar todos los proyectos con target `build` y los migra a todos.
- Los monorepos Nx se detectan via `nx.json` y usan `nx build` en lugar de `ng build`.
- `@angular/build` (paquete de build desde Angular 17) se detecta y actualiza automáticamente si ya está presente en el proyecto.

---

## Qué hacer si la migración se detiene

El script para y muestra el reporte HTML cuando un build falla y el auto-fix no pudo resolverlo. En ese caso:

1. Abrí el reporte en `.migrate_reports/migration_report_*.html`
2. Revisá `last_build_error.log` para ver el error completo
3. Corregí el problema manualmente en tu código
4. Volvé a ejecutar el script — **reanuda automáticamente desde el último paso exitoso**

Si el proyecto quedó en un estado inconsistente, podés restaurar el snapshot anterior:

```bash
python ng_migrate.py --restore latest
```

También podés saltar directamente a un paso específico:

```bash
python ng_migrate.py --from-version 17
```

---

## Limitaciones conocidas

Estas situaciones **no se resuelven automáticamente** y requieren intervención manual:

| Limitación | Descripción |
|------------|-------------|
| **Errores de TypeScript en el código** | Cambios de API entre versiones de Angular (métodos deprecados, firmas modificadas). El script indica dónde falla pero no modifica lógica de negocio. |
| **Librerías de terceros no listadas** | Paquetes fuera de la lista de detección automática pueden tener migraciones propias que el script no ejecuta. Revisarlas manualmente con `ng update <paquete>`. |
| **Auto-fix solo cubre NG8001 y NG8002** | Otros errores de compilación Angular (errores de tipado, imports circulares, providers deprecados) no se parchean automáticamente. |
| **Módulos muy complejos con `imports` dinámicos** | Lazy loading con strings, `loadChildren`, módulos condicionales o generados dinámicamente pueden necesitar ajuste manual. |
| **Proyectos con `paths` custom en tsconfig** | Si el proyecto usa alias de rutas complejos, el auto-fix de imports puede generar rutas relativas incorrectas. |
| **SSR / Universal** | El target `:server` se compila con `--check-ssr` pero no se aplican migraciones específicas de SSR automáticamente. |
| **`--standalone` en módulos complejos** | El codemod de Standalone puede requerir revisión manual en módulos con providers, forRoot/forChild o bootstrapping personalizado. |

---

## Posibles mejoras

Áreas donde el script puede evolucionar. Contribuciones bienvenidas:

- [ ] **Modo dry-run** — mostrar qué pasos ejecutaría sin modificar nada
- [ ] **Auto-fix extendido** — cubrir más errores: NG0100, imports circulares, providers deprecados
- [ ] **Reporte mejorado** — incluir sugerencias de fix para cada error, no solo el log crudo
- [ ] **Soporte multi-app avanzado** — migrar apps en el mismo workspace en orden de dependencia
- [ ] **Validación previa** — chequear antes de empezar si hay breaking changes conocidos en dependencias
- [ ] **Integración con CI** — modo no-interactivo con exit codes claros para usar en pipelines

---

## Contribuciones

Issues y pull requests son bienvenidos. Si encontrás un caso de migración no cubierto por el script, abrí un issue con:
- Versión de Angular de origen
- Salida de `last_build_error.log`
- Fragmentos relevantes de `angular.json` / `package.json`

---

## Licencia

MIT
