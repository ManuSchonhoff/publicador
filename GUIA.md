# Publicador automático de @trackearpro · guía paso a paso

**Qué hace:** GitHub mira cada 15 minutos la lista `cola.json` y publica lo que vos **aprobaste** y cuya hora **ya pasó**: carruseles, imágenes, reels **e historias** (sección 10). Usa la API oficial de Instagram. Tu compu puede estar apagada.
**Qué no hace:** stickers en las historias (link, encuesta, cuenta regresiva, preguntas), compartir un posteo en la historia, fijar ni destacadas. Lo que se puede reemplazar ya está reemplazado (sección 10); el resto, sección 11.

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
2. `python preparar.py todo` → suma como **borrador** el feed **y las historias** de cada día de `2026-10-07/carga/` (salta los que esperan video, lo ya aprobado y las historias cuya hora ya pasó). Para un día solo: `python preparar.py 2026-10-21`.
3. `python verificar.py` → muestra qué sale y cuándo, cuántas piezas hay por día (feed + historias) y frena lo que esté mal (fechas impresas, pie largo, más de 30 hashtags, WhatsApp, nombres reales, @trackear.pro con punto, cepo/ARCA/UIF/cuevas, formato de las placas, del video o de la historia).
4. `python aprobar.py 2026-10-14` (aprueba el feed y las historias de ese día) o `python aprobar.py semana`. Una historia sola: `python aprobar.py 2026-10-21_h2`. **Solo lo aprobado se publica.**
5. GitHub Desktop → *Summary:* `Aprobado 14/10` → **Commit to main** → **Push origin**. **Sin Push, GitHub no se entera.**

Para frenar una pieza aprobada: `python aprobar.py --volver 2026-10-14` y después Commit + Push.

**Reels:** cuando el video editado pasa la revisión, se copia a la carpeta del día como `video.mp4` (lo dice el `ESPERA-VIDEO.txt` de cada día). Después, pasos 2 a 5 con esa fecha.

**Cómo sale:** el cron de GitHub dice "cada 15 minutos", pero en la práctica corre cada 3 a 5 horas (así salió tarde el 15/10). Por eso: (1) cada Push que cambia `cola.json` (una aprobación) arranca una corrida en el momento, (2) cada corrida que encuentra algo aprobado para las próximas 5 h 30 min espera hasta esa hora y lo publica, y (3) después de publicar, si hay algo más aprobado dentro de los 90 minutos (por ejemplo historias de las 20:35 y 20:40), espera y lo publica en la misma corrida. Una pieza de las 20:30 sale entre las 20:30 y las 20:32, siempre que haya habido una corrida o una aprobación en las 5 h 30 min anteriores. Si por algo no salió en 3 horas (o pasó el día), **no sale**: queda en `error` para que no aparezca un precio "vigente al 16/10" el 17. Nunca se publica dos veces: cada pieza queda marcada como `publicado` con su link, se guarda el número del "contenedor" de Instagram antes de publicar, y antes de reintentar se fija si ya salió.

**Dónde mirar:** `registro.txt` en el repo (una línea por publicación o error) y la pestaña **Actions**. Si una pieza quedó en `error`: arreglá lo que diga, `python aprobar.py <fecha>` y Commit + Push.

## 10. Historias: salen solas

Desde ahora las historias se publican igual que el feed: las arma `preparar.py`, las revisás con `verificar.py`, las aprobás con `aprobar.py` y GitHub las sube a su hora. No hace falta que estés para escribir nada ni para poner un link.

**Qué sale solo.** Una imagen de 1080 × 1920 (PNG o JPG; se pasa a JPEG) o un video vertical de 3 a 60 segundos (MP4 o MOV, hasta 100 MB). Sin pie y sin texto alternativo (Instagram no los tiene en historias). Cada historia tiene su id, `<fecha>_h<orden>` (por ejemplo `2026-10-21_h2`), su hora y su orden.

**De dónde salen.** De la lista "historias" del `dia.json` de cada día (orden, hora, archivo, sticker). Si un día no tiene `dia.json`, de los archivos `historia-1_….png`, `historia-2_….png`… del paquete, a la hora de `hora.txt`.

**Varias a la misma hora:** salen en orden. Primero el posteo del feed y después las historias 1, 2, 3…

**Lo que la API no deja y cómo quedó resuelto** (fuente: documentación oficial de Meta, "IG User Media" y "Content Publishing" de la API de Instagram, consultada el 21/10/2026; textual: *"Publishing stickers (i.e., link, poll, location) is not supported"*):

| En el plan decía | Qué hace ahora el publicador |
|---|---|
| **Compartir la publicación del día** (avión de papel → "Agregar a tu historia", con o sin texto encima) | La API no comparte posteos. Arma sola la historia **"Nuevo en el perfil"**: la tapa del posteo en un marco de vidrio, el título y "Miralo en el perfil de @trackearpro.". Sale **después** del posteo y **solo si el posteo salió** (si el posteo falla, esa historia queda en `error` y no aparece anunciando algo que no está). |
| **Sticker de link** ("Probalo 7 días gratis", "Ver cómo") | Usa la variante **`__auto`** de la placa, con el pedido impreso en vidrio: **"El link está en el perfil."** Ya están hechas `oferta_h4__auto.png` y `2026-10-19_h2_2000-pruebas__auto.png` (en `disenos/historias/png/`). Las originales no se tocaron. |
| **Encuesta, cuenta regresiva, caja de preguntas** | No hay forma por la API. `preparar.py` no las sube y te avisa: van a mano a su hora, o se hace una variante `__auto` sin sticker (por ejemplo "Contestanos por mensaje") y sale sola. |
| **Texto escrito en la app, música, mención con sticker** | Tampoco. Todo texto tiene que venir impreso en la imagen. |

**Lo que revisa `verificar.py` en cada historia:** que sea 9:16 (imagen JPEG hasta 8 MB, o video de 3 a 60 s y hasta 100 MB, H.264 o HEVC), que no tenga pie, que no quede un sticker pendiente, y el **texto de la imagen** (lo saca solo del HTML de la placa) con las mismas reglas que los pies: nada de WhatsApp, nombres reales, "cada 4 horas", @trackear.pro, cepo/ARCA/UIF/cuevas ni fechas de otro día. Si no encuentra el HTML de una imagen, te avisa para que la mires a ojo antes de aprobar.

**Tope de 25 por día.** La API cuenta todo lo que se publica en 24 horas corridas, historias incluidas. Nos fijamos un tope de **25** (Meta documenta 50 o 100 según la página; dejamos margen). `verificar.py` te muestra cuántas hay por día (`jue 29/10 1+4` = 1 del feed y 4 historias) y avisa si un día se pasa. Si igual se pasa, lo que sobra espera a la corrida siguiente y, si se atrasa más de 3 horas, no sale.

**Una historia suelta** (una imagen o un video que no está en ningún paquete):

```
python preparar.py historia "C:\ruta\a\la\imagen.png" --fecha 2026-10-29 --hora 20:30
```

Opcional: `--orden 2` (su lugar entre las de esa hora), `--texto "lo que dice la imagen"` (si no tiene HTML), `--depende-de 2026-10-29` (que salga solo si salió ese posteo). Después, `python aprobar.py 2026-10-29_h2` y Commit + Push.

**"Nuevo en el perfil" para cualquier posteo, a mano** (por ejemplo para mirarla antes):

```
python "C:\Users\manus\Documents\TrackeAR Marketing\_herramientas\historia_nuevo_en_perfil.py" --paquete 2026-10-27
```

Toma la tapa (`01.png` o `portada.png`) y el título: el texto que el plan mandaba escribir arriba del posteo compartido; si no hay, la primera oración del pie. Para poner otro título, dejá un `titulo-historia.txt` en la carpeta del día con el texto, y volvé a correr `python preparar.py <fecha>`. Necesita internet la primera vez (la tipografía Inter).

**Las historias duran 24 horas.** Las **destacadas** se siguen armando a mano.

## 11. Lo que la API no hace: va a mano

- **Stickers** de las historias (encuesta, caja de preguntas, cuenta regresiva, link si no hay variante `__auto`). `preparar.py` te dice cuáles quedaron afuera; siguen el `historias.md` de cada día.
- **Fijar** publicaciones (los `FIJAR.txt` del 16 y 23/10) y sumar a **destacadas**.
- **Música de la biblioteca de Instagram**: el reel sale con el audio que trae el video (está bien: la música es de uso libre).
- **Etiquetas de producto** (Shopping), filtros y el **recorte de la portada en la grilla**.
- El **texto alternativo de los reels y de las historias** (en carruseles sí lo carga, placa por placa).
- Contestar comentarios y mensajes: ManyChat contesta `GANANCIA`; el resto, vos (quedate de 20:30 a 21:00 los días de feed a la noche).

## 12. Si falla la renovación del token

GitHub te abre un aviso ("issue") en el repo y te llega un mail. Arreglo rápido: paso 6 (token nuevo) y actualizá el secreto `IG_TOKEN`.

Si el aviso dice que Instagram dio un token nuevo y falta `GH_PAT`, y querés que se guarde solo: github.com → tu foto → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token** → nombre `renovar token IG`, *Resource owner* el dueño del repo, *Expiration* 1 año, **Only select repositories** → `trackear-instagram` → *Repository permissions* → **Secrets: Read and write** → **Generate token** → copialo y cargalo como tercer secreto `GH_PAT` (paso 7).

## Plan B (si el miércoles a las 18:00 no está andando)

Publicá a mano desde `2026-10-07/carga/2026-10-14/` (placas `01.png` a `08.png`, `pie.txt`, `alt.txt`), como dice `hora.txt`. Si esa pieza estaba aprobada, sacale la aprobación (`python aprobar.py --volver 2026-10-14` + Commit + Push) para que GitHub no la intente después. Si igual la intentara, ve que el pie ya está en la cuenta y no la repite.

---

**Archivos:** `cola.json` (la lista) · `preparar.py` · `verificar.py` (prueba sin internet) · `aprobar.py` · `publicar.py` (lo corre GitHub) · `renovar_token.py` · `.github/workflows/` (los dos automáticos) · `media/` (las placas y las historias en JPEG y los videos que baja Instagram) · `registro.txt`. Fuera del repo: `_herramientas/historia_nuevo_en_perfil.py` y su plantilla `2026-10-07/disenos/historias/_plantilla_nuevo-en-el-perfil.html`.
