# Revify CRM — Production Candidate

Esta versión sustituye la persistencia del navegador por una API FastAPI + PostgreSQL.

## Incluye
- Login con token firmado.
- PostgreSQL como fuente de verdad.
- Un único lead de prueba si `SEED_DEMO_LEAD=true`.
- Dashboard en cero al arrancar: visitas, demos, ventas y facturación se calculan desde datos reales.
- Paginación por cursor de 50 leads.
- Índices por comercial, código postal, estado, categoría y fecha.
- Búsqueda de leads desde servidor.
- Audit log append-only.
- Ventas idempotentes para evitar duplicados por doble clic o reintento.
- Healthcheck `/api/health`.
- Dockerfile y configuración para Railway.

## Local
`docker compose up --build`

Abre `http://localhost:8080`
Usuario local: `demo@revify.local`
Contraseña local: `demo`

## Producción
Configura `APP_ENV=production`, PostgreSQL y secretos según `.env.production.example`.
No uses las credenciales demo.

## Importante
El despliegue real y los backups dependen del proveedor de hosting. La aplicación está preparada para PostgreSQL, pero hay que conectar un hosting para tener una URL pública y backups externos.
