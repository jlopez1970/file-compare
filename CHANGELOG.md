# Changelog — File Comparison Tool

Todos los cambios importantes de `file_compare.py` se registran aquí.

**Formato de versión:** `vMM.mm`
- **MM (mayor):** cambios grandes o que rompen compatibilidad, por ejemplo opciones renombradas o un formato de exportación distinto.
- **mm (menor):** funciones nuevas, mejoras y correcciones que no rompen nada.

Cada vez que cambies de versión, actualiza también `__version__` en `file_compare.py` y la versión que aparece en `HELP.md`.

**Categorías para cada entrada:** Agregado · Cambiado · Corregido · Eliminado

---

## [Sin publicar]

### Agregado
- **Recordar la última selección de carpetas.** Se guarda en `~/.file_compare.json`:
  - el modo y las carpetas A y B
  - las últimas 10 carpetas usadas
  - los patrones de exclusión, las casillas de opciones y la última estrategia de limpieza

  La interfaz gráfica carga todo esto al abrir. Los campos de carpeta ahora son listas desplegables con las carpetas recientes, y **Elegir...** abre en la carpeta actual. La línea de comandos también guarda la selección.
- **Limpiar duplicados.** Deja un archivo por grupo y elimina el resto.
  - **CLI:** `dupes --clean` con las opciones `--keep {oldest,newest,shortest,first}`, `--dry-run`, `--permanent` y `-y/--yes`. Muestra el plan y pide confirmación antes de eliminar.
  - **GUI:** botón **Limpiar duplicados...** con selector de estrategia, opción mover o borrar, vista previa en colores (conservar/eliminar) y confirmación.
  - Por defecto los archivos se mueven a `<carpeta>/_duplicados_eliminados/<fecha_hora>/` con un `registro.csv`.
  - Antes de eliminar cada archivo se vuelve a verificar su contenido con SHA-256.
- **Omitir grupos completos al limpiar.**
  - **GUI:** cada grupo de la vista previa tiene una casilla (☑ / ☐). Un clic en la fila del grupo, o la barra espaciadora, lo omite o lo vuelve a incluir. También hay botones **Marcar todos** y **Desmarcar todos**. Los grupos omitidos se ven en gris y sus archivos dicen *SIN CAMBIOS*. El total se actualiza al instante y **Limpiar** se desactiva si no queda nada marcado.
  - **CLI:** `--skip-groups LISTA` (ej. `2,5` o `3-7,10`) con los números del reporte.
  - Los números de grupo ahora son fijos y no cambian al omitir grupos.
- **Filtro "Solo incluir"** para buscar solo ciertos archivos, por ejemplo `*.jpg, *.png` o `Fotos`.
  - **CLI:** `--include PATRON` (o `--only`), se puede repetir.
  - **GUI:** campo **Solo incluir** encima de **Excluir**; se guarda con la última selección.
  - Usa los mismos tipos de patrón que la exclusión y tampoco distingue mayúsculas. Un archivo entra si el patrón coincide con el archivo o con cualquier carpeta que lo contiene.
  - Se combina con la exclusión: primero se incluye y después se excluye; la exclusión siempre gana.
  - Funciona en `dupes`, `--clean`, `compare` y `samename`.
- **Comando `restore`** y botón **Restaurar...** para deshacer una limpieza a partir de la carpeta de cuarentena. Nunca sobrescribe archivos que ya existan.

### Cambiado
- La carpeta `_duplicados_eliminados` se excluye siempre de los escaneos.
- `HELP.md` se actualizó con las nuevas funciones.

### Corregido
- **La exclusión en la búsqueda no funcionaba en varios casos.** Antes solo funcionaba con nombres simples escritos con las mismas mayúsculas, como `node_modules` o `*.JPG`. Ahora:
  - no distingue mayúsculas: `*.jpg` excluye `IMG.JPG`
  - acepta una barra al final: `node_modules/`
  - acepta rutas relativas: `Fotos/2024`, `docs/*`, `*/cache`
  - acepta rutas completas: `/Users/.../carpeta` o `~/Desktop/carpeta`
  - en la GUI, los patrones también se pueden separar con `;`

  Afecta a `dupes`, `--clean`, `compare` y `samename`.

---

## [v01.00] — 2026-11-20

Primera versión.

### Agregado
- **`dupes`:** encuentra archivos con exactamente el mismo contenido en una carpeta y sus subcarpetas. Compara en tres pasos: tamaño, hash parcial de 64 KB y SHA-256 completo. Los grupos se ordenan por espacio recuperable.
- **`compare`:** compara dos carpetas y separa los archivos en idénticos, distintos, solo en A, solo en B y movidos/renombrados (mismo contenido en otra ruta).
- **`samename`:** encuentra archivos con el mismo nombre y distinto contenido. La opción `--ignore-case` trata nombres con distintas mayúsculas como iguales.
- **Línea de comandos** con `argparse`. Opciones comunes:
  - `--exclude` (se puede repetir)
  - `--include-hidden`
  - `--follow-symlinks`
  - `--json` y `--csv`
  - `-q` / `--quiet`
- `--min-size` en `dupes`. Por defecto vale 1, así que ignora los archivos vacíos.
- `-V` / `--version`.
- **Interfaz gráfica (tkinter):**
  - selector de modo y selección de carpetas
  - patrones de exclusión
  - búsqueda en segundo plano con barra de progreso
  - resultados en árbol
  - exportar a CSV o JSON
  - abrir la ubicación del archivo con doble clic
- Al correr el script sin argumentos se abre la interfaz gráfica.
- Si falta `tkinter`, el script lo avisa y se puede seguir usando la línea de comandos.
- `HELP.md` con la ayuda completa y este `CHANGELOG.md`.
