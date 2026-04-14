# ng_migrate — Angular 13 → 20

Script Python para migrar proyectos Angular de la versión 13 a la 20 de forma automática, paso a paso, sin usar `npx`. Compatible con npm, pnpm y yarn, proyectos CLI y monorepos Nx, Angular Material, y con sistema de snapshots, reportes HTML y auto-corrección de errores de build.

---

## Características

- **Migración paso a paso** v14 → v15 → v16 → v17 → v18 → v19 → v20, validando build de producción en cada salto
- **Auto-detección** del gestor de paquetes (npm / pnpm / yarn) y de monorepos Nx
- **Pin de TypeScript** por versión de Angular — asigna la versión exacta compatible antes de cada salto
- **Snapshots ZIP** antes y después de cada versión — modos `full`, `lite` u `off`
- **Reporte HTML** con diff de `package.json` y salida de build por cada paso
- **Auto-fix inteligente** — parsea errores de build (NG8001 / NG8002) y parchea imports de módulos Angular automáticamente
- **Normalizador de MaterialModule** — reescribe/crea `material.module.ts` compatible con Angular 14+
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
| Node.js   | ≥ 20.19 (recomendado 22.x) |
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
                   [--check-ssr] [--restore RESTORE]

opciones:
  -h, --help                  muestra esta ayuda y sale
  --snapshot {full,lite,off}  modo de snapshot (por defecto: lite)
  --standalone                aplica codemods Standalone
  --control-flow              convierte *ngIf/*ngFor/*ngSwitch a @if/@for/@switch
  --material-mdc              aplica migración MDC (Material)
  --material-m3               genera base de tema Material 3
  --check-ssr                 intenta compilar el target :server si existe (SSR)
  --restore RESTORE           restaura snapshot: nombre.zip o 'latest'
```

### Ejemplos

```bash
# Migración básica (snapshots lite, sin codemods)
python ng_migrate.py

# Migración completa con todos los codemods modernos
python ng_migrate.py --standalone --control-flow --material-mdc --material-m3

# Sin snapshots (más rápido, menos espacio en disco)
python ng_migrate.py --snapshot off

# Snapshots completos (incluye todos los archivos del proyecto)
python ng_migrate.py --snapshot full

# Volver al último snapshot guardado
python ng_migrate.py --restore latest

# Volver a un snapshot específico
python ng_migrate.py --restore .migrate_backups/20250910-120000_pre_v16.zip
```

---

## Cómo funciona

```
Angular 13
    │
    ├── snapshot pre_v14
    ├── Pin TypeScript ~4.6.4
    ├── ng update @angular/core@14 @angular/cli@14
    ├── ng update @angular/material@14
    ├── install + dedupe
    ├── Build de producción → auto-fix si falla → reintento
    └── snapshot post_v14
    │
    ├── (igual para v15, v16, v17)
    │
    ├── snapshot pre_v18
    ├── Migración al application builder (v18+)
    ├── Build de producción...
    └── snapshot post_v18
    │
    ├── (v19, v20)
    │
    ├── Codemods opcionales (standalone, control-flow, MDC, M3)
    ├── Actualización de terceros (rxjs ^7.8, zone.js ^0.14)
    ├── ng lint --fix
    └── Build final → reporte HTML
```

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
| `.migrate_state.json`   | Estado interno (índice de snapshots) |
| `last_build_error.log`  | Salida cruda del último build fallido — útil para depurar |

---

## Motor de auto-fix

Cuando un build falla, el script:

1. Parsea `last_build_error.log` buscando errores de plantillas Angular:
   - **NG8001** — elemento desconocido → importa el módulo correcto o añade `CUSTOM_ELEMENTS_SCHEMA`
   - **NG8002** — propiedad desconocida → importa los módulos de Material (tabla, paginador, sort) según corresponda
2. Aplica los fixes directamente en los archivos `*.module.ts` afectados
3. Reintenta el build una vez
4. Si sigue fallando, escribe el reporte HTML y sale con mensaje de error claro

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
4. Volvé a ejecutar el script — va a retomar desde el último salto de versión exitoso

Si el proyecto quedó en un estado inconsistente, podés restaurar el snapshot anterior:

```bash
python ng_migrate.py --restore latest
```

---

## Limitaciones conocidas

Estas situaciones **no se resuelven automáticamente** y requieren intervención manual:

| Limitación | Descripción |
|------------|-------------|
| **Errores de TypeScript en el código** | Cambios de API entre versiones de Angular (métodos deprecados, firmas modificadas). El script indica dónde falla pero no modifica lógica de negocio. |
| **Librerías de terceros con breaking changes** | Paquetes como `@ngrx/*`, `@ngneat/*`, `@ngx-translate/*`, Angular Fire, etc. pueden tener migraciones propias que este script no ejecuta. |
| **No retoma desde un paso intermedio** | Si el proceso para en v17, al volver a ejecutar recorre desde v14. Usar snapshots para no perder el trabajo ya hecho. |
| **Auto-fix solo cubre NG8001 y NG8002** | Otros errores de compilación Angular (NG0XXX, errores de tipado, imports circulares) no se parchean automáticamente. |
| **Módulos muy complejos con `imports` dinámicos** | Lazy loading con strings, `loadChildren`, módulos condicionales o generados dinámicamente pueden necesitar ajuste manual. |
| **Proyectos con `paths` custom en tsconfig** | Si el proyecto usa alias de rutas complejos, el auto-fix de imports puede generar rutas relativas incorrectas. |
| **SSR / Universal** | El target `:server` se intenta compilar con `--check-ssr` pero no se aplican migraciones específicas de SSR automáticamente. |
| **`--standalone` en módulos complejos** | El codemod de Standalone funciona en la mayoría de los casos pero puede requerir revisión manual en módulos con providers, forRoot/forChild o bootstrapping personalizado. |

---

## Posibles mejoras

Áreas donde el script puede evolucionar. Contribuciones bienvenidas:

- [ ] **`--from-version N`** — reanudar la migración desde un salto específico sin necesidad de restaurar snapshot
- [ ] **Modo dry-run** — mostrar qué pasos ejecutaría sin modificar nada
- [ ] **Auto-fix extendido** — cubrir más errores: NG0100 (ExpressionChangedAfterItHasBeenChecked), imports circulares, providers deprecados
- [ ] **Detección de librerías populares** — ejecutar automáticamente `ng update @ngrx/store`, `ng update @angular/fire`, etc. si están presentes
- [ ] **Reporte mejorado** — incluir sugerencias de fix para cada error, no solo el log crudo
- [ ] **Soporte multi-app avanzado** — migrar apps en el mismo workspace en orden de dependencia
- [ ] **Validación previa** — chequear antes de empezar si hay breaking changes conocidos en dependencias de terceros
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
