# Checklist legal antes de producción

Las páginas legales se publican inicialmente como borrador. No debe cambiarse
`LEGAL_DRAFT_MODE=false` hasta validar, como mínimo, lo siguiente:

- `LEGAL_BUSINESS_NAME`: nombre completo de la persona física o moral responsable.
- `LEGAL_BUSINESS_ADDRESS`: domicilio físico completo que se publicará.
- `LEGAL_SUPPORT_PHONE`: teléfono real para aclaraciones y reclamaciones.
- `LEGAL_CONTACT_EMAIL`: buzón monitoreado para privacidad, cancelaciones y soporte.
- `LEGAL_AUDIO_RETENTION_NOTICE`: conservación real de audio, texto y resultados.
- Proveedores que reciben datos: pagos, infraestructura, correo, seguridad y soporte.
- Plazos de conservación de cuentas, facturación, registros técnicos y respaldos.
- Flujo de solicitud y respuesta para derechos ARCO.
- Consentimiento expreso para cobros recurrentes antes de contratar.
- Aviso de renovación automática al menos cinco días naturales antes del cobro.
- Mecanismo de cancelación inmediata y evidencia de la fecha de solicitud.
- Precios totales, impuestos, periodicidad y fecha de cobro antes del Checkout.
- Enlaces de privacidad, términos y reembolsos configurados en Stripe Checkout.

## Variables de entorno provisionales

```text
LEGAL_DRAFT_MODE=true
LEGAL_BUSINESS_NAME=CouperTech Demo, S.A. de C.V. (DATO DUMMY)
LEGAL_BUSINESS_ADDRESS=Av. Ejemplo 123, Col. Centro, C.P. 00000, Ciudad de México, México (DATO DUMMY)
LEGAL_SUPPORT_PHONE=+52 55 0000 0000 (DATO DUMMY)
LEGAL_CONTACT_EMAIL=contacto@coupertech.com
LEGAL_LAST_UPDATED=23 de agosto de 2026
LEGAL_AUDIO_RETENTION_NOTICE=DATO DUMMY: eliminación dentro de 24 horas.
```

Los textos deben recibir revisión profesional antes de aceptar pagos reales. La
lista ayuda a preparar la revisión, pero no sustituye asesoría jurídica.
