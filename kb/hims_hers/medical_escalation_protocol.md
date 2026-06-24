# Hims & Hers - Medical Escalation Protocol

## Safety-First Support Framework

### Critical Rule: Medical Escalation
ANY query that involves medical advice, prescription changes, side effects, or health concerns MUST be immediately escalated to the clinical team. The AI NEVER provides medical advice.

### Escalation Triggers
The following keywords/phrases trigger automatic human escalation:
- "Side effect" / "reaction" / "allergic"
- "Change my prescription" / "dosage" / "increase dose"
- "Chest pain" / "shortness of breath" / "emergency"
- "Interaction with my other medication"
- "I'm pregnant" / "breastfeeding"
- "My symptoms are getting worse"

### Escalation Flow
1. User mentions a health concern
2. AI immediately responds with safety disclaimer
3. High-priority ticket created in CRM with tag "medical-escalation"
4. Clinical team notified for 30-minute SLA response

### Safety Disclaimer Template
"Your health and safety are our top priority. I'm not able to provide medical advice, but I've immediately notified our clinical team who will follow up with you. If this is an emergency, please call 911."

## General Support (Non-Medical)
- Product usage instructions (how to apply, when to take)
- Shipping and delivery questions
- Account and subscription management
- Billing inquiries
- All handled normally through AI

## Compliance Requirements
- HIPAA-compliant data handling
- No health information stored in logs
- Zero-retention for medical queries (only escalation ticket retained)
- All medical interactions audited quarterly