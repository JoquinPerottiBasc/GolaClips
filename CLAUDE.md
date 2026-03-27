# GolaClips - Contexto del Proyecto

## Qué es este proyecto
GolaClips es un MVP (Producto Mínimo Viable) de un SaaS que genera automáticamente highlights de videos de deportes de acción (GoPro, DJI, etc). El usuario sube un video largo, la IA lo analiza y detecta los momentos más emocionantes, y FFmpeg corta esos momentos en clips descargables.

Esta es la primera versión. Vamos a ir agregando funcionalidades de forma incremental después de que el MVP funcione. Tené eso en cuenta: no sobre-engineerear, no agregar cosas que no se pidieron.

## Stack Tecnológico
- Frontend: HTML + CSS + JS vanilla, servido por FastAPI desde `/frontend`
- Backend: Python + FastAPI + FFmpeg + Google Gemini API
- Auth: Firebase Auth (Google OAuth) + firebase-admin en backend
- Storage: Cloudflare R2 (boto3)
- DB: SQLite (golaclips.db) — migración a PostgreSQL pendiente

## Modelo de negocio
- Sistema de CRÉDITOS: 1 crédito = 1 minuto de video (redondeado hacia arriba)
- Plan Free: 30 créditos/mes, clips con marca de agua "GolaClips" (FFmpeg drawtext), clips se borran a los 3 días
- Plan Pro: 200 créditos/mes ($12/mes), sin marca de agua, clips se borran a los 30 días
- Créditos se resetean el 1° de cada mes — NO se acumulan, siempre vuelven al total del plan
- Upgrade a Pro: por ahora se hace manualmente cambiando `plan = 'pro'` en la DB
- Stripe: columnas reservadas en DB pero integración pendiente

## Reglas de código
- Comentarios en el código: siempre en inglés
- Mensajes de commits: siempre en inglés, descriptivos
- Commits pequeños y frecuentes
- Componentes pequeños y reutilizables
- Siempre manejar errores claramente
- Mantenerlo simple — esto es un MVP

## Autonomía
- Ser proactivo: cuando algo está roto o es mejorable, arreglarlo directamente sin preguntar
- No hacer preguntas del tipo "¿cómo lo hacemos?" o "¿qué preferís?" — tomar la mejor decisión técnica y ejecutarla
- Solo preguntar cuando hay una decisión de negocio o de producto que el usuario debe tomar (ej: "¿querés 5 clips o 10?")
- Si hay varias opciones técnicas válidas, elegir la más simple y seguir adelante

## Importante: la persona con quien trabajo
La persona que trabaja en este proyecto NO es desarrollador ni técnico. Entiende la lógica bien pero no escribe código. Por lo tanto:
- Cuando haya que instalar algo, dar el comando exacto para correr
- Cuando haya que completar un archivo de config (como .env), explicar exactamente qué va en cada campo y cómo conseguir cada valor
- Si algo falla, explicar qué pasó en términos simples y qué hacer
- Nunca asumir que el usuario sabe qué hacer después — siempre terminar la respuesta con un "próximo paso" claro
- Responderle al usuario siempre en español