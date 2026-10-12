# Publicador automático de @trackearpro · guía paso a paso

**Qué hace:** GitHub mira cada 15 minutos la lista `cola.json` y publica en el feed (carruseles, imágenes y reels) lo que vos **aprobaste** y cuya hora **ya pasó**. Usa la API oficial de Instagram. Tu compu puede estar apagada.
**Qué no hace:** historias, fijar, destacadas ni nada de lo de la sección 9. Eso sigue a mano.

Tiempo total de la puesta en marcha: unos 40 minutos. Para salir el **miércoles 14/10 a las 20:30**, terminala antes del miércoles a las 18:00. Si no llegás, ese día publicás a mano desde `2026-10-07/carga/2026-10-14/` (ver "Plan B" al final).

> El repo es **público** (así Instagram puede bajar las imágenes): cualquiera que lo encuentre ve las placas y los pies antes de que salgan. Ahí nunca va un token ni una contraseña: esos van solo en los "secretos" del paso 7.

---

## 1. Subir esta carpeta a GitHub (con GitHub Desktop)

1. **Recomendado:** que el repo no quede con tu nombre personal. En github.com, arriba a la derecha **+** → **New organization** → **Free** → nombre `trackearpro`, email `trackearpro@gmail.com` → **Next** → **Complete setup**. (Si preferís tu usuario, salteá esto.)
2. Bajá e instalá **GitHub Desktop** desde desktop.github.com. Abrilo e iniciá sesión con tu cuenta de GitHub.
3. **File** → **Add local repository…** → **Choose…** → elegí `C:\Users\manus\Documents\TrackeAR Marketing\publicador` → **Add repository**.
4. Va a decir que no es un repositorio: tocá el link **create a repository** → dejá todo como está → **Create repository**.
5. Si en **Changes** aparecen archivos: abajo a la izquierda, en *Summary*, escribí `Primera carga` → **Commit to main**.
6. Arriba, **Publish repository** →
   - *Name:* `trackear-instagram`
   - **destildá "Keep this code private"** (tiene que ser público)
   - *Organization:* `trackearpro` (si hiciste el paso 1)
   - **Publish repository**.

> Alternativa sin GitHub Desktop (solo para la primera vez): en github.com, **+** → **New repository** → nombre `trackear-instagram`, **Public** → **Create repository** → link **uploading an existing file** → arrastrá **todo lo que hay adentro** de la carpeta `publicador` (incluida `.github`) → **Commit changes**. No sirve para el uso de todas las semanas y no acepta archivos de más de 25 MB (los reels): usá GitHub Desktop.

## 2. @trackearpro tiene que ser cuenta profesional de Empresa

En el celu, Instagram → tu perfil → **☰** → **Tipo de cuenta y herramientas**.
- Si dice **Cambiar a cuenta profesional**: tocalo → categoría **Software** → **Empresa** → **Listo**.
- Si ya ves **Cambiar a cuenta personal**, ya es profesional. Mirá que sea **Empresa** y no Creador (si dice Creador: **Cambiar a cuenta de empresa**).

## 3. Crear la app en Meta para desarrolladores

1. Entrá a **developers.facebook.com** con tu Facebook. Si es la primera vez: **Comenzar** y seguí los pasos (verifica tu cuenta).
2. **Mis apps** → **Crear app**.
3. *Nombre de la app:* `TrackeAR Publicador` · *Email:* `trackearpro@gmail.com` → **Siguiente**.
4. *Casos de uso:* elegí **Administrar mensajes y contenido en Instagram** → **Siguiente**.
5. *Empresa:* **Todavía no quiero conectar un portfolio comercial** → **Siguiente** → **Siguiente** → **Ir al panel** (o **Crear app**). Si te pide la contraseña de Facebook, la ponés vos.

## 4. Sumar Instagram y los permisos

1. En el panel de la app: **Casos de uso** → en "Administrar mensajes y contenido en Instagram" tocá **Personalizar**.
2. Entrá a **Configuración de la API con inicio de sesión de Instagram** (*API setup with Instagram login*).
3. En **Permisos**, que estén **instagram_business_basic** e **instagram_business_content_publish**. Si alguno dice **Agregar**, tocalo.

No hace falta "Revisión de la app" ni pasarla a modo público: alcanza con que tu cuenta sea evaluadora (paso 5).

## 5. Agregar @trackearpro como evaluador

1. En el panel: **Roles de la app** → **Roles** → **Agregar personas** → **Evaluador de Instagram** (*Instagram Tester*) → escribí `trackearpro` → **Agregar**.
2. En la compu, entrá a **instagram.com/accounts/manage_access/** con @trackearpro → pestaña **Invitaciones de evaluador** → **Aceptar**.

## 6. Generar el token largo y copiar el ID

1. Volvé a **Configuración de la API con inicio de sesión de Instagram** → **1. Generar tokens de acceso** → **Agregar cuenta** → entrás con @trackearpro → **Permitir**.
2. Aparece la cuenta con un **número** (el ID) y el botón **Generar token**. Tocá **Generar token**, tildá que entendés → **copiá el token** (empieza con `IG…`; se muestra una sola vez).
3. Pegá los dos (token e ID) en un bloc de notas **solo un momento**: van al paso 7 y después borrás el bloc. No los mandes por chat ni por mail.

Ese token dura 60 días; GitHub lo renueva solo el día 1 de cada mes (sección 8).

## 7. Cargar los 2 secretos en GitHub

En github.com → tu repo `trackear-instagram` → **Settings** → menú izquierdo **Secrets and variables** → **Actions** → **New repository secret**:

| Name | Secret |
|---|---|
| `IG_TOKEN` | el token del paso 6 |
| `IG_USER_ID` | el número (ID) del paso 6 |

**Add secret** en cada uno. Listo: borrá el bloc de notas.

## 8. Primera prueba: "solo probar" (no publica nada)

1. En el repo → pestaña **Actions**. Si aparece un botón verde **I understand my workflows, go ahead and enable them**, tocalo.
2. A la izquierda **Publicar en Instagram** → a la derecha **Run workflow** → dejá tildado **Solo probar** → **Run workflow**.
3. Esperá un minuto, entrá a la corrida → **publicar** → abrí el paso **Publicar**. Tiene que decir:
   - `Token OK: es la cuenta @trackearpro`
   - `Permiso para publicar OK`
   - `los 8 archivo(s) se pueden bajar desde GitHub` (por cada pieza)
   - `Prueba terminada: todo en orden.`
4. Si dice que el token no anda: repetí el paso 6 y actualizá el secreto (**Settings → Secrets and variables → Actions → IG_TOKEN → Update**).

Probá también la renovación: **Actions** → **Renovar token de Instagram** → **Run workflow**. Tiene que decir `Token renovado: vale 60 días más.` (Instagram pide que el token tenga al menos 24 h; si lo generaste hoy, probalo mañana.)

Avisos: GitHub te manda un mail cuando una corrida falla. Mirá que esté prendido en github.com → tu foto → **Settings** → **Notifications** → **Actions** → *Email*, *Only notify for failed workflows*.

---

## 9. Lo de todas las semanas (5 minutos)

Abrí la carpeta `publicador` en el Explorador, hacé clic en la barra de dirección, escribí `cmd` y Enter. En esa ventana:

1. **Antes de nada:** GitHub Desktop → **Fetch origin** → **Pull origin** (trae la `cola.json` que actualizó GitHub al publicar).
2. `python preparar.py todo` → suma como **borrador** cada día de `2026-10-07/carga/` que tenga feed (salta los de solo historias y los que esperan video). Para uno solo: `python preparar.py 2026-10-21`.
3. `python verificar.py` → muestra qué sale y cuándo, y frena lo que esté mal (fechas impresas, pie largo, más de 30 hashtags, WhatsApp, nombres reales, formato de las placas o del video).
4. `python aprobar.py 2026-10-14` (o `python aprobar.py semana`). **Solo lo aprobado se publica.**
5. GitHub Desktop → *Summary:* `Aprobado 14/10` → **Commit to main** → **Push origin**. **Sin Push, GitHub no se entera.**

Para frenar una pieza aprobada: `python aprobar.py --volver 2026-10-14` y después Commit + Push.

**Reels:** cuando el video editado pasa la revisión, se copia a la carpeta del día como `video.mp4` (lo dice el `ESPERA-VIDEO.txt` de cada día). Después, pasos 2 a 5 con esa fecha.

**Cómo sale:** GitHub corre en los minutos 4, 19, 34 y 49 de cada hora, y a veces se atrasa unos minutos. Una pieza de las 20:30 sale entre las 20:34 y las 20:50. Si por algo no salió en 3 horas (o pasó el día), **no sale**: queda en `error` para que no aparezca un precio "vigente al 16/10" el 17. Nunca se publica dos veces: cada pieza queda marcada como `publicado` con su link, y antes de publicar se fija si ese pie ya está en la cuenta.

**Dónde mirar:** `registro.txt` en el repo (una línea por publicación o error) y la pestaña **Actions**. Si una pieza quedó en `error`: arreglá lo que diga, `python aprobar.py <fecha>` y Commit + Push.

## 10. Lo que la API no hace: va a mano

- **Historias**, todas: con encuesta, caja de preguntas, link, cuenta regresiva o cualquier sticker. Siguen el `historias.md` de cada día.
- **Fijar** publicaciones (los `FIJAR.txt` del 16 y 23/10) y sumar a **destacadas**.
- **Música de la biblioteca de Instagram**: el reel sale con el audio que trae el video (está bien: la música es de uso libre).
- **Etiquetas de producto** (Shopping), filtros y el **recorte de la portada en la grilla**.
- El **texto alternativo de los reels** (en carruseles sí lo carga, placa por placa).
- Contestar comentarios y mensajes: ManyChat contesta `GANANCIA`; el resto, vos (quedate de 20:30 a 21:00 los días de feed a la noche).

## 11. Si falla la renovación del token

GitHub te abre un aviso ("issue") en el repo y te llega un mail. Arreglo rápido: paso 6 (token nuevo) y actualizá el secreto `IG_TOKEN`.

Si el aviso dice que Instagram dio un token nuevo y falta `GH_PAT`, y querés que se guarde solo: github.com → tu foto → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token** → nombre `renovar token IG`, *Resource owner* el dueño del repo, *Expiration* 1 año, **Only select repositories** → `trackear-instagram` → *Repository permissions* → **Secrets: Read and write** → **Generate token** → copialo y cargalo como tercer secreto `GH_PAT` (paso 7).

## Plan B (si el miércoles a las 18:00 no está andando)

Publicá a mano desde `2026-10-07/carga/2026-10-14/` (placas `01.png` a `08.png`, `pie.txt`, `alt.txt`), como dice `hora.txt`. Si esa pieza estaba aprobada, sacale la aprobación (`python aprobar.py --volver 2026-10-14` + Commit + Push) para que GitHub no la intente después. Si igual la intentara, ve que el pie ya está en la cuenta y no la repite.

---

**Archivos:** `cola.json` (la lista) · `preparar.py` · `verificar.py` (prueba sin internet) · `aprobar.py` · `publicar.py` (lo corre GitHub) · `renovar_token.py` · `.github/workflows/` (los dos automáticos) · `media/` (las placas en JPEG y los videos que baja Instagram) · `registro.txt`.
