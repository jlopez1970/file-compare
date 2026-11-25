# File Comparison Tool — Ayuda

**Versión:** v01.00 + cambios sin publicar (ver `CHANGELOG.md`)
**Archivo:** `file_compare.py`
**Requisitos:** Python 3.8 o superior. Solo usa la librería estándar. La interfaz gráfica necesita `tkinter`.

---

## Contenido

1. [Qué hace](#qué-hace)
2. [Instalación](#instalación)
3. [Uso rápido](#uso-rápido)
4. [Modo línea de comandos (CLI)](#modo-línea-de-comandos-cli)
   - [dupes — archivos duplicados](#dupes--archivos-duplicados)
   - [Limpiar duplicados (--clean)](#limpiar-duplicados---clean)
   - [restore — deshacer una limpieza](#restore--deshacer-una-limpieza)
   - [compare — comparar dos carpetas](#compare--comparar-dos-carpetas)
   - [samename — mismo nombre, distinto contenido](#samename--mismo-nombre-distinto-contenido)
   - [Opciones comunes](#opciones-comunes)
5. [Modo interfaz gráfica (GUI)](#modo-interfaz-gráfica-gui)
6. [Última selección de carpetas](#última-selección-de-carpetas)
7. [Exportar resultados](#exportar-resultados)
8. [Cómo funciona la comparación](#cómo-funciona-la-comparación)
9. [Preguntas frecuentes y problemas](#preguntas-frecuentes-y-problemas)

---

## Qué hace

| # | Función | Comando |
|---|---------|---------|
| 1 | Encuentra archivos con **exactamente el mismo contenido** dentro de una carpeta y sus subcarpetas | `dupes` |
| 2 | **Compara dos carpetas**: idénticos, distintos, solo en A, solo en B, movidos/renombrados | `compare` |
| 3 | Identifica **dos o más archivos con el mismo nombre y distinto contenido** | `samename` |
| 4 | Se puede correr desde la **línea de comandos**, sin interfaz gráfica | todos |
| 5 | Se puede correr con **interfaz gráfica** | `gui` o sin argumentos |

Además puede **limpiar los duplicados**: deja un archivo por grupo y mueve el resto a una carpeta de cuarentena, de donde se pueden restaurar. También puede borrarlos definitivamente si lo pides.

Fuera de la limpieza, la herramienta **solo lee** los archivos. Los comandos de búsqueda no borran, mueven ni modifican nada.

---

## Instalación

No hay que instalar paquetes. Copia `file_compare.py` a cualquier carpeta.

Para la interfaz gráfica, `tkinter` ya viene con Python en Windows y macOS. En Linux puede faltar:

```bash
# Debian / Ubuntu
sudo apt install python3-tk
# Fedora
sudo dnf install python3-tkinter
```

Para ver la versión instalada:

```bash
python file_compare.py --version
```

---

## Uso rápido

```bash
python file_compare.py dupes    ~/Documentos
python file_compare.py compare  ./respaldo_2025 ./respaldo_2026
python file_compare.py samename ~/Proyectos
python file_compare.py gui
```

En Windows usa `py` o `python` según tu instalación, por ejemplo `py file_compare.py dupes C:\Users\Jesus\Fotos`.

---

## Modo línea de comandos (CLI)

```
python file_compare.py [-h] [-V] {dupes,compare,samename,gui} ...
```

Para ver la ayuda de cada comando: `python file_compare.py <comando> -h`

### dupes — archivos duplicados

Busca archivos con contenido idéntico en una carpeta y todas sus subcarpetas, sin importar el nombre del archivo.

```bash
python file_compare.py dupes <carpeta> [--min-size BYTES] [opciones comunes]
```

| Opción | Descripción |
|--------|-------------|
| `--min-size BYTES` | Ignora archivos más pequeños que este tamaño. Por defecto es `1`, así que los archivos vacíos se ignoran. Usa `0` para incluirlos. |

**Ejemplo de salida:**

```
1 grupos de duplicados - espacio recuperable: 5 B

Grupo 1: 2 archivos de 5 B (sha256 133ee989293f)
    /tmp/t/A/sub/copia.txt
    /tmp/t/A/x.txt
```

Los grupos salen ordenados por **espacio recuperable**, es decir, el tamaño multiplicado por el número de copias extra.

### Limpiar duplicados (--clean)

Deja **un archivo por grupo** y elimina las demás copias.

```bash
python file_compare.py dupes <carpeta> --clean [--keep ESTRATEGIA] [--dry-run] [--permanent] [-y]
```

| Opción | Descripción |
|--------|-------------|
| `--clean` | Activa la limpieza. Primero muestra el plan (qué se conserva y qué se elimina) y pide confirmación. |
| `--keep ESTRATEGIA` | Qué archivo conservar en cada grupo. Por defecto es `oldest`. |
| `--skip-groups LISTA` | Grupos que **no** se limpian, con el número que aparece en el reporte. Acepta listas y rangos, por ejemplo `2,5` o `3-7,10`. Los números que no existen se ignoran con un aviso. |
| `--dry-run` | Solo muestra el plan, sin eliminar nada |
| `--permanent` | Borra definitivamente en vez de mover a cuarentena. **No se puede deshacer.** |
| `-y`, `--yes` | No pide confirmación, útil en scripts. Sin terminal interactiva y sin `--yes`, la limpieza se cancela. |

Estrategias de `--keep`:

| Valor | Conserva |
|-------|----------|
| `oldest` | El archivo con la fecha de modificación más antigua |
| `newest` | El archivo con la fecha de modificación más reciente |
| `shortest` | El archivo con la ruta más corta, normalmente el que está menos anidado |
| `first` | El primero en orden alfabético de ruta |

**Qué pasa con los archivos eliminados.** Por defecto se **mueven** a:

```
<carpeta>/_duplicados_eliminados/<fecha_hora>/
```

- Se conserva la ruta relativa original dentro de esa carpeta.
- Ahí también queda un `registro.csv` con cada archivo movido, el archivo que se conservó y el hash.
- La carpeta `_duplicados_eliminados` **nunca se escanea**, así que no aparece como duplicado en búsquedas futuras.
- Cuando estés seguro de que no necesitas esos archivos, puedes borrar esa carpeta a mano.

**Seguridad.** Justo antes de eliminar cada archivo se vuelve a verificar su contenido con SHA-256. Si un archivo cambió o desapareció desde la búsqueda, se salta y se reporta como `[aviso]`.

**Ejemplo:**

```bash
python file_compare.py dupes ~/Fotos --clean --keep shortest --dry-run   # ver el plan
python file_compare.py dupes ~/Fotos --clean --keep shortest             # ejecutar (pide confirmación)
python file_compare.py dupes ~/Fotos --clean --skip-groups 2,5           # limpiar todo menos los grupos 2 y 5
```

Los números de grupo son fijos: salen de `dupes` sin `--clean` o de `--dry-run`, y no cambian al omitir grupos.

```
Plan de limpieza - se conserva: la ruta mas corta
Se van a MOVER a '_duplicados_eliminados' 3 archivos (15 B).

Grupo 1:
    CONSERVAR  /tmp/t/A/x.txt
    ELIMINAR   /tmp/t/A/sub/copia.txt
    ELIMINAR   /tmp/t/A/sub/copia2.txt
...
Eliminados: 3 archivos - espacio liberado: 15 B
Movidos a: /tmp/t/A/_duplicados_eliminados/20261120_132735
Para deshacer: python file_compare.py restore "/tmp/t/A/_duplicados_eliminados/20261120_132735"
```

### restore — deshacer una limpieza

Devuelve a su ruta original los archivos que una limpieza movió a cuarentena.

```bash
python file_compare.py restore "<carpeta>/_duplicados_eliminados/<fecha_hora>"
```

- Lee el `registro.csv` de esa carpeta.
- Si ya existe un archivo en la ruta original, **no lo sobrescribe**; lo reporta como aviso.
- Los archivos borrados con `--permanent` no se pueden restaurar.

### compare — comparar dos carpetas

Compara dos carpetas por **ruta relativa** y contenido.

```bash
python file_compare.py compare <carpetaA> <carpetaB> [opciones comunes]
```

Resultados:

| Categoría | Significado |
|-----------|-------------|
| **Idénticos** | Misma ruta relativa y mismo contenido en A y B |
| **Distintos** | Misma ruta relativa pero distinto contenido |
| **Solo en A** | Existe en A pero no en B, en esa ruta |
| **Solo en B** | Existe en B pero no en A, en esa ruta |
| **Movidos / renombrados** | Un archivo "solo en A" que tiene el mismo contenido que uno o más archivos "solo en B" |

**Ejemplo de salida:**

```
Identicos: 1   Distintos: 1   Solo en A: 4   Solo en B: 1   Movidos/renombrados: 1

== DISTINTOS (misma ruta, distinto contenido) ==
    sub/d.txt
== MOVIDOS / RENOMBRADOS (mismo contenido) ==
    A:solo.txt  ->  B:sub/movido.txt
```

### samename — mismo nombre, distinto contenido

Busca archivos que tienen el **mismo nombre** en distintas subcarpetas pero **contenido diferente**. Sirve para encontrar versiones distintas de un mismo documento.

```bash
python file_compare.py samename <carpeta> [--ignore-case] [opciones comunes]
```

| Opción | Descripción |
|--------|-------------|
| `--ignore-case` | Trata `Foto.JPG` y `foto.jpg` como el mismo nombre |

Si todos los archivos con un mismo nombre tienen idéntico contenido, **no** aparecen; esos se encuentran con `dupes`.

**Ejemplo de salida:**

```
n.txt  (2 versiones distintas)
    [fcedfee4a23f]        4 B  /tmp/t/A/n.txt
    [d9f86d34b0b0]        4 B  /tmp/t/A/sub/n.txt
```

### Opciones comunes

Estas opciones sirven en `dupes`, `compare` y `samename`:

| Opción | Descripción |
|--------|-------------|
| `--include PATRON` (o `--only`) | **Solo** busca los archivos que coincidan. Se puede repetir: `--include "*.jpg" --include "*.png"`. Sin esta opción se buscan todos los archivos. Ver [Solo incluir + excluir](#solo-incluir--excluir). |
| `--exclude PATRON` | Excluye archivos o carpetas. Se puede repetir: `--exclude .git --exclude "*.tmp"`. Ver [Patrones de exclusión](#patrones-de-exclusión). |
| `--include-hidden` | Incluye archivos y carpetas ocultos (los que empiezan con `.`). Por defecto se ignoran. |
| `--follow-symlinks` | Sigue enlaces simbólicos. Por defecto se ignoran. |
| `--json ARCHIVO` | Guarda el resultado en JSON |
| `--csv ARCHIVO` | Guarda el resultado en CSV |
| `-q`, `--quiet` | No muestra mensajes de progreso |
| `-h`, `--help` | Muestra la ayuda |
| `-V`, `--version` | Muestra la versión (opción global, va antes del comando) |

Los mensajes de progreso y los avisos salen por *stderr*, y los resultados por *stdout*. Así puedes redirigir solo los resultados:

```bash
python file_compare.py dupes ~/Fotos > reporte.txt
```

### Patrones de exclusión

Lo que se excluye no se escanea, no se compara y nunca se limpia. Si excluyes una carpeta, se salta todo lo que tiene dentro.

Los patrones **no distinguen mayúsculas**: `*.jpg` también excluye `IMG.JPG`. Aceptan los comodines `*` (cualquier texto) y `?` (un carácter). La barra al final es opcional: `node_modules` y `node_modules/` funcionan igual.

| Tipo de patrón | Ejemplo | Qué excluye |
|----------------|---------|-------------|
| Nombre | `node_modules`, `.git`, `*.tmp`, `Thumbs.db` | Cualquier archivo o carpeta con ese nombre, a cualquier profundidad |
| Ruta relativa (contiene `/`) | `Fotos/2024`, `docs/*`, `*/cache` | Esa ruta dentro de la carpeta escaneada, también si está más adentro. Por ejemplo, `Fotos/2024` excluye `Fotos/2024` y `Backup/Fotos/2024`. |
| Ruta completa | `/Users/jesus/Desktop/viejo`, `~/Desktop/viejo` | Exactamente esa carpeta o archivo |

En la línea de comandos usa un `--exclude` por patrón y pon comillas a los que llevan `*`, para que la terminal no los expanda: `--exclude "*.jpg"`.

### Solo incluir + excluir

Con **Solo incluir** (`--include`) limitas la búsqueda a ciertos archivos, y con **Excluir** quitas algunos de esos. El orden es siempre el mismo:

1. **Solo incluir:** se quedan únicamente los archivos que coinciden con algún patrón de la lista. Si la lista está vacía, se quedan todos.
2. **Excluir:** de esos, se quitan los que coinciden con algún patrón de exclusión. **La exclusión siempre gana.**

Los patrones de *Solo incluir* son del mismo tipo que los de exclusión (nombre, ruta relativa o ruta completa) y tampoco distinguen mayúsculas. Un archivo entra si el patrón coincide con **el archivo o con cualquier carpeta que lo contiene**:

| Solo incluir | Qué entra |
|--------------|-----------|
| `*.jpg` | Solo las fotos JPG, en cualquier carpeta |
| `*.jpg, *.png, *.heic` | Fotos JPG, PNG y HEIC |
| `Fotos` | Todos los archivos dentro de cualquier carpeta llamada `Fotos` |
| `Fotos/2024` | Todos los archivos dentro de `Fotos/2024` |
| `docs/*, *.pdf` | Lo que esté dentro de `docs`, más cualquier PDF |

**Ejemplos combinados:**

```bash
# Solo fotos JPG y PNG, pero no las de Fotos/2024 ni las miniaturas
python file_compare.py dupes ~/Pictures --include "*.jpg" --include "*.png" --exclude "Fotos/2024" --exclude "*thumb*"

# Solo lo que esté en carpetas "Proyectos", sin node_modules ni .tmp
python file_compare.py dupes ~/Desktop --only Proyectos --exclude node_modules --exclude "*.tmp"

# Comparar dos respaldos mirando solo documentos
python file_compare.py compare ./respaldo1 ./respaldo2 --include "*.docx" --include "*.pdf" --include "*.xlsx"
```

Los dos filtros se aplican a todos los modos: `dupes`, `--clean`, `compare` y `samename`. Lo que queda fuera por cualquiera de los dos no se escanea, no se compara y nunca se limpia.

---

## Modo interfaz gráfica (GUI)

```bash
python file_compare.py gui
# o simplemente
python file_compare.py
```

1. **Modo:** elige *Duplicados*, *Comparar dos carpetas* o *Mismo nombre, distinto contenido*.
2. **Carpeta A** (y **Carpeta B** en el modo comparar): escribe la ruta, usa **Elegir...** o abre la lista desplegable con las últimas 10 carpetas usadas. Al abrir el programa ya aparece la última selección.
3. **Solo incluir:** si lo llenas, solo se buscan los archivos que coinciden, por ejemplo `*.jpg, *.png` o `Fotos`. Vacío significa todos. Ver [Solo incluir + excluir](#solo-incluir--excluir).
   **Excluir:** patrones separados por coma o punto y coma, por ejemplo `.git, __pycache__; *.tmp, Fotos/2024`. No se separan por espacios, porque un nombre puede tener espacios. Ver [Patrones de exclusión](#patrones-de-exclusión).
4. **Incluir ocultos** e **Ignorar mayúsculas en nombres**, esta última solo en el modo *samename*.
5. Pulsa **Ejecutar**. La búsqueda corre en segundo plano y la barra inferior muestra el progreso.
6. Los resultados aparecen en un árbol agrupado.
   - **Doble clic** o **Abrir ubicación** abre la carpeta del archivo seleccionado.
   - **Exportar CSV / Exportar JSON** guarda el último resultado.
7. **Limpiar duplicados...** se activa después de una búsqueda en modo *Duplicados* que encontró resultados. Abre una ventana donde:
   - eliges qué archivo conservar en cada grupo
   - eliges entre **mover a cuarentena** (por defecto) o **borrar definitivamente**
   - ves la vista previa: en verde lo que se **CONSERVA** y en rojo lo que se **ELIMINA**, con el total de archivos y espacio
   - **omites grupos completos.** Cada grupo tiene una casilla (☑ / ☐):
     - un **clic en la fila del grupo** lo omite o lo vuelve a incluir. El grupo omitido queda en gris y sus archivos dicen *SIN CAMBIOS*.
     - la **barra espaciadora** hace lo mismo con los grupos seleccionados. Sirve aunque tengas seleccionado un archivo del grupo, y se pueden seleccionar varios con Shift o Cmd/Ctrl.
     - **Marcar todos** y **Desmarcar todos** cambian todos a la vez. Un truco útil: *Desmarcar todos* y luego marcar solo los grupos que quieres limpiar.
     - el total de abajo se actualiza al instante. Si no queda ningún grupo marcado, **Limpiar** se desactiva.

   Al pulsar **Limpiar** se pide confirmación. Cuando termina, la búsqueda se repite sola para mostrar el estado actual.
8. **Restaurar...** te deja elegir una carpeta `_duplicados_eliminados/<fecha_hora>` y devuelve sus archivos a su lugar.

---

## Última selección de carpetas

El programa recuerda la última selección, tanto si lo usas desde la interfaz como desde la línea de comandos. Se guarda en:

```
~/.file_compare.json
```

Qué guarda:

- el último modo usado
- la Carpeta A y la Carpeta B
- las últimas 10 carpetas usadas
- los patrones de *Solo incluir* y de exclusión, y las casillas *Incluir ocultos* e *Ignorar mayúsculas*
- la última estrategia de limpieza elegida

Al abrir la interfaz gráfica todo esto se carga automáticamente. Para empezar desde cero, borra ese archivo.

---

## Exportar resultados

### CSV

| Modo | Columnas |
|------|----------|
| `dupes` | `grupo, sha256, tamano_bytes, ruta` |
| `compare` | `estado, ruta_relativa, detalle`. El estado puede ser `identico`, `distinto`, `solo_en_A`, `solo_en_B` o `movido`. |
| `samename` | `nombre, hash, tamano_bytes, ruta` |

### JSON

Es la estructura completa del resultado, útil para procesarlo con otros scripts.

- `dupes`: lista de `{hash, size, count, wasted, files[]}`
- `compare`: `{folder_a, folder_b, only_in_a[], only_in_b[], identical[], different[], moved_or_renamed[]}`
- `samename`: lista de `{name, versions, files[{path, size, hash, modified}]}`

---

## Cómo funciona la comparación

- **El contenido se compara con SHA-256.** Dos archivos se consideran iguales solo si su contenido es idéntico byte por byte. El nombre y la fecha no importan.
- **Optimización en `dupes`:** primero agrupa por tamaño, luego compara un hash parcial de los primeros 64 KB y solo al final calcula el hash completo. Así se evita leer completos los archivos que no pueden ser duplicados.
- Los archivos se leen en bloques de 1 MB, de modo que se pueden procesar archivos muy grandes sin llenar la memoria.
- Los archivos que no se pueden leer, por ejemplo por permisos, se reportan como `[aviso]` y se saltan.

---

## Preguntas frecuentes y problemas

**"tkinter no está disponible"**
Instala `python3-tk` (ver [Instalación](#instalación)) o usa el modo CLI.

**¿Por qué no aparecen mis archivos ocultos o la carpeta `.git`?**
Por defecto se ignoran. Usa `--include-hidden`.

**¿Por qué no aparecen archivos vacíos en `dupes`?**
Todos los archivos vacíos son "iguales" entre sí, así que se ignoran por defecto. Usa `--min-size 0` para incluirlos.

**Es lento en carpetas muy grandes.**
El tiempo depende sobre todo de cuántos archivos tienen el mismo tamaño, porque esos se tienen que leer. Usa `--exclude` para saltar carpetas que no te interesan y `--min-size` para ignorar archivos pequeños.

**¿Puede borrar los duplicados?**
Sí, con `dupes --clean` o con el botón **Limpiar duplicados...** (ver [Limpiar duplicados](#limpiar-duplicados---clean)). Por defecto los mueve a cuarentena para que puedas deshacer la limpieza.

**¿Cómo libero el espacio de verdad después de limpiar?**
Mover a cuarentena no libera espacio en disco. Cuando revises que todo está bien, borra la carpeta `_duplicados_eliminados`. También puedes usar `--permanent` desde el principio.

**Al restaurar dice "Ya existe un archivo en la ruta original".**
Por seguridad no se sobrescribe nada. Mueve o renombra el archivo que está en esa ruta y vuelve a correr `restore`.
