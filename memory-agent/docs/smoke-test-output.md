# Smoke test: memory and multi-turn agent

Model `us.anthropic.claude-opus-5-5` on Amazon Bedrock · store `dynamodb` · producer `P-PE-008` · synthetic sample data only

## A. One exchange, from the open question to a draft

**Agent:**

> Hola, y gracias por su tiempo. Soy el asistente de Intercambio de Productores de Fair Trade USA. ¿Qué ha sido lo más difícil para usted o su organización últimamente?

### Turn 1

**Producer:**

> La lluvia ha sido muy irregular y la última cosecha de banano bajó mucho.

**Agent:**

> Entiendo. Una lluvia tan irregular y una cosecha que baja mucho es un golpe fuerte.
> 
> ¿Desde cuándo nota usted que la lluvia está así de irregular? ¿Y cuánto bajó la última cosecha comparada con una cosecha normal?

Memory after this turn: stage `clarify` · understanding v1 · missing ['onset', 'severity', 'actions_tried', 'location_checked', 'entity_type_checked'] · confirmed False · evidence 0 · notes 0 · log 5 events · staged facts [] · PII []

Model runs: clarify[record_understanding] → clarify[text]

### Turn 2

**Producer:**

> Por cierto, ¿nuestra última auditoría de certificación salió bien?

**Agent:**

> Esa pregunta no la puedo responder. Este asistente no tiene acceso a los resultados de auditorías ni al estado de certificación. Para eso, lo mejor es consultar directamente con su contacto de certificación.
> 
> Volviendo a la lluvia y la cosecha: ¿desde cuándo nota que la lluvia está tan irregular? ¿Y cuánto bajó la última cosecha comparada con una normal?

Memory after this turn: stage `clarify` · understanding v1 · missing ['onset', 'severity', 'actions_tried', 'location_checked', 'entity_type_checked'] · confirmed False · evidence 0 · notes 0 · log 8 events · staged facts [] · PII []

Model runs: clarify[text]

### Turn 3

**Producer:**

> Entiendo. Lo de la lluvia empezó hace dos temporadas y perdimos como un 30% de la cosecha. Hemos probado regar a mano, pero no alcanza el agua. El comité de agua ya le pidió ayuda a la municipalidad. Nuestro técnico Carlos Ramírez, 312 555 0199, también lo vio.

**Agent:**

> Gracias por contarme todo esto. Perder un 30% de la cosecha en dos temporadas es muy duro. También es importante saber que el riego a mano no alcanza, y que el comité de agua ya pidió ayuda a la municipalidad.
> 
> Para buscar datos y ejemplos que sirvan en su caso, quiero confirmar dos cosas:
> 
> - ¿Siguen trabajando en Piura, Perú?
> - ¿La Asociación Valle del Chira sigue siendo una asociación de pequeños productores con unos 330 miembros?

Memory after this turn: stage `clarify` · understanding v2 · missing ['location_checked', 'entity_type_checked'] · confirmed False · evidence 0 · notes 1 · log 14 events · staged facts [] · PII [['NAME', 'PHONE']]

Model runs: clarify[record_understanding] → clarify[text]

### Turn 4

**Producer:**

> Sí, estamos en Piura y somos una asociación de pequeños productores.

**Agent:**

> Gracias. Le resumo lo que entendí:
> 
> Desde hace dos temporadas la lluvia ha sido muy irregular, y en la última cosecha de banano perdieron cerca de un 30%. Probaron regar a mano, pero el agua no alcanza. El comité de agua ya pidió ayuda a la municipalidad, y su técnico, Carlos Ramírez, también vio el problema. Están en Piura, Perú, y son la Asociación Valle del Chira, una asociación de pequeños productores.
> 
> ¿Es correcto, o hay algo que quiera corregir o agregar?

Memory after this turn: stage `playback` · understanding v3 · missing nothing · confirmed False · evidence 0 · notes 1 · log 19 events · staged facts [] · PII [['NAME', 'PHONE']]

Model runs: clarify[record_understanding] → playback[text]

### Turn 5

**Producer:**

> Casi. Desde este año ya no somos asociación, somos una cooperativa de unas 350 familias.

**Agent:**

> Gracias por la corrección. Este es el resumen actualizado:
> 
> Desde hace dos temporadas la lluvia ha sido muy irregular. En la última cosecha de banano perdieron cerca de un 30%. Probaron regar a mano, pero el agua no alcanza. El comité de agua ya pidió ayuda a la municipalidad, y su técnico, Carlos Ramírez, también vio el problema. Están en Piura, Perú. Desde este año son una cooperativa de unas 350 familias.
> 
> ¿Ahora está bien así?

Memory after this turn: stage `playback` · understanding v4 · missing nothing · confirmed False · evidence 0 · notes 1 · log 24 events · staged facts [('entity_type', 'cooperative'), ('member_count', '350')] · PII [['NAME', 'PHONE']]

Model runs: playback[record_understanding] → playback[text]

### Turn 6

**Producer:**

> Sí, ahora es correcto.

**Agent:**

> [Borrador, aún sin verificar]
> 
> Gracias por confirmar. Esto es lo que muestran los datos para el banano en Piura y lo que hicieron otras organizaciones parecidas.
> 
> 1. Los datos regionales coinciden con lo que ustedes vivieron: en las últimas dos temporadas, la lluvia en Piura estuvo un 31% por debajo del promedio de 10 años.
>    Fuentes: CHIRPS v2.0 rainfall (SYNTHETIC STAND-IN)
>    Normas relacionadas: APS (ILLUSTRATIVE PLACEHOLDER) APS-DEMO-4.1
> 2. La presión sobre el agua en la zona ya es extremadamente alta. Según la proyección, seguirá extremadamente alta hacia 2030.
>    Fuentes: WRI Aqueduct 4.0 (SYNTHETIC STAND-IN)
>    Normas relacionadas: APS (ILLUSTRATIVE PLACEHOLDER) APS-DEMO-2.1
> 3. No son los únicos. En la encuesta de 2025, con 99 respuestas, los problemas más mencionados fueron el agua, el clima y el acceso a financiamiento. El 54% dijo que su rendimiento bajó. Ustedes ya plantaron árboles de sombra en 2022, pero mantenerlos costó más de lo planeado. Y su fondo de crédito rotatorio para insumos y emergencias sigue en marcha.
>    Fuentes: Encuesta 2025; Proyecto Premium: Shade-tree planting; Proyecto Premium: Revolving credit fund
>    Normas relacionadas: APS (ILLUSTRATIVE PLACEHOLDER) APS-DEMO-4.1
> 4. La Plantación La Esperanza, en Colombia, también produce banano. En 2022 instaló tanques para guardar agua de lluvia y cubrir los meses secos. Costó unos 31.000 dólares y reportan menos días de cosecha perdidos. Es una finca con trabajadores contratados, no una cooperativa.
>    Fuentes: Plantación La Esperanza (Colombia)
>    Normas relacionadas: APS (ILLUSTRATIVE PLACEHOLDER) APS-DEMO-2.1
> 5. La Cooperativa Cumbre Azul, en Honduras, produce café. En 2022 instaló tanques de agua de lluvia en las casas y en los viveros. Costó unos 43.000 dólares y cerca de dos tercios de los socios los adoptaron.
>    Fuentes: Cooperativa Cumbre Azul (Honduras)
>    Normas relacionadas: APS (ILLUSTRATIVE PLACEHOLDER) APS-DEMO-2.1
> 
> Lo que los datos no cubren:
> - No tengo ejemplos de organizaciones de Piura o de Perú que hayan enfrentado este mismo problema.
> - No tengo datos de cuánta agua juntan los tanques cuando llueve tan poco como en Piura estas temporadas.
> - No tengo información sobre la ayuda que el comité de agua pidió a la municipalidad, ni sobre otros apoyos públicos.
> - No tengo datos sobre formas de riego que gasten menos agua en el banano.
> 
> Ustedes conocen mejor que nadie sus parcelas y a sus familias, así que la decisión sobre qué hacer es de la cooperativa.

Memory after this turn: stage `drafted` · understanding v4 · missing nothing · confirmed True · evidence 13 · notes 1 · log 35 events · staged facts [('entity_type', 'cooperative'), ('member_count', '350')] · PII [['NAME', 'PHONE']]

Model runs: playback[confirm_understanding] → retrieve[get_producer_record, get_regional_context, search_peer_examples, retrieve_standards] → draft[submit_guidance]

### Turn 7

**Producer:**

> ¿Cuánto ha bajado la lluvia en nuestra zona?

**Agent:**

> En las últimas dos temporadas, la lluvia en Piura estuvo un **31% por debajo** del promedio de los últimos 10 años.
> 
> Esto coincide con lo que ustedes vivieron: el problema empezó hace dos temporadas.
> 
> Este dato es para la región de Piura, no solo para sus parcelas. No tengo el detalle mes por mes ni las fechas exactas de las temporadas medidas.

Memory after this turn: stage `drafted` · understanding v4 · missing nothing · confirmed True · evidence 13 · notes 1 · log 38 events · staged facts [('entity_type', 'cooperative'), ('member_count', '350')] · PII [['NAME', 'PHONE']]

Model runs: drafted[text]

### Checks

- PASS: the exchange reached the draft stage
- PASS: the correction created a new understanding version
- PASS: the corrected entity type is staged as a profile fact
- PASS: the fact records when it became true, as the producer said it
- PASS: the final version, not the first one, is what the producer confirmed
- PASS: nothing was retrieved before the producer confirmed
- PASS: the draft has an insight
- PASS: the draft has a peer example
- PASS: every citation resolves to this session's evidence ledger
- PASS: the named person and phone number raised a PII flag
- PASS: the producer's words were not redacted
- PASS: a detail that fits no slot was kept as a session note
- PASS: no near-duplicate quotes were saved
- PASS: the out-of-scope audit question stayed out of structured memory
- PASS: the event log holds every tool call and each run's exact prompt
- PASS: no durable profile write happened during the conversation

## B. Durable commit, then human review

`commit_memory(consent_granted=True)` stands in for the future consent stage. It writes pending records only.

A new exchange **before review** would be given this memory:

```text
<producer_profile>
organization: Asociación Valle del Chira
location (from the registered record): Piura, Peru
crops: banana
entity_type: small producer association (registered)
member_count: 330 (registered)
</producer_profile>

<working_memory>
You opened this conversation by saying: Hola, y gracias por su tiempo. Soy el asistente de Intercambio de Productores de Fair Trade USA. ¿Qué ha sido lo más difícil para usted o su organización últimamente?
{
 "version": 0,
 "missing_slots": [
  "challenge",
  "onset",
  "severity",
  "actions_tried",
  "tags",
  "location_checked",
  "entity_type_checked"
 ],
 "awaiting_confirmation": false,
 "confirmed": false,
 "challenge": null,
 "onset": null,
 "severity": null,
 "actions_tried": null,
 "tags": [],
 "producer_quotes": [],
 "notes": [],
 "location_checked": false,
 "entity_type_checked": false,
 "profile_facts": []
}
</working_memory>
```

- PASS: pending facts are invisible to other exchanges
- PASS: the pending episode is not available as evidence
- PASS: the records wait in the review queue
- PASS: the PII flag travels with the episode to the reviewer

A reviewer now handles the queue:

- approve `member_count` = `350`, since "este año", supported by: "somos una cooperativa de unas 350 familias"
- approve `entity_type` = `cooperative`, since "este año", supported by: "Desde este año ya no somos asociación, somos una cooperativa de unas 350 familias."
- approve the episode (1 notes, PII: ['NAME', 'PHONE'])

## C. A return visit after review

A new exchange is now given this memory:

```text
<producer_profile>
organization: Asociación Valle del Chira
location (from the registered record): Piura, Peru
crops: banana
entity_type: cooperative (reviewed, since: este año)
member_count: 350 (reviewed, since: este año)
</producer_profile>

<past_reviewed_exchanges>
Reviewed accounts of earlier conversations. Use them for continuity, but listen first: the producer may be describing something different today.
- 2026-11-03: La lluvia ha sido muy irregular y la última cosecha de banano bajó mucho. (tried: Regar a mano, pero no alcanza el agua, El comité de agua pidió ayuda a la municipalidad; notes: El técnico de la organización también observó el problema.)
</past_reviewed_exchanges>

<working_memory>
You opened this conversation by saying: Hola, y gracias por su tiempo. Soy el asistente de Intercambio de Productores de Fair Trade USA. ¿Qué ha sido lo más difícil para usted o su organización últimamente?
{
 "version": 0,
 "missing_slots": [
  "challenge",
  "onset",
  "severity",
  "actions_tried",
  "tags",
  "location_checked",
  "entity_type_checked"
 ],
 "awaiting_confirmation": false,
 "confirmed": false,
 "challenge": null,
 "onset": null,
 "severity": null,
 "actions_tried": null,
 "tags": [],
 "producer_quotes": [],
 "notes": [],
 "location_checked": false,
 "entity_type_checked": false,
 "profile_facts": []
}
</working_memory>
```

**Agent:**

> Hola, y gracias por su tiempo. Soy el asistente de Intercambio de Productores de Fair Trade USA. ¿Qué ha sido lo más difícil para usted o su organización últimamente?

### Turn 1

**Producer:**

> Hola de nuevo. Seguimos con problemas de agua: este año la quebrada se secó en agosto y perdimos otro 20% de la cosecha. Probamos con un reservorio pequeño, pero no alcanzó.

**Agent:**

> Hola de nuevo, gracias por contarnos. Este año la quebrada se secó en agosto, perdieron otro 20% de la cosecha de banano y el reservorio pequeño no alcanzó.
> 
> Antes de buscar qué hicieron otros productores, quiero confirmar dos datos. ¿Siguen en Piura, Perú? ¿Y siguen siendo una cooperativa de 350 socios?

Memory after this turn: stage `clarify` · understanding v1 · missing ['location_checked', 'entity_type_checked'] · confirmed False · evidence 0 · notes 0 · log 5 events · staged facts [] · PII []

Model runs: clarify[record_understanding] → clarify[text]

### Turn 2

**Producer:**

> Sí, seguimos en Piura y seguimos siendo cooperativa, pero ya somos 360 familias.

**Agent:**

> Gracias. Les repito lo que entendí, para que me corrijan si algo no está bien.
> 
> En la Asociación Valle del Chira siguen con problemas de agua. En agosto de este año la quebrada se secó y perdieron otro 20% de la cosecha de banano. Probaron con un reservorio pequeño, pero no alcanzó. Siguen en Piura, Perú, y siguen siendo una cooperativa, ahora de 360 familias.
> 
> ¿Es correcto, o hay algo que quiera cambiar o agregar?

Memory after this turn: stage `playback` · understanding v2 · missing nothing · confirmed False · evidence 0 · notes 0 · log 10 events · staged facts [('member_count', '360')] · PII []

Model runs: clarify[record_understanding] → playback[text]

### Turn 3

**Producer:**

> Sí, es correcto.

**Agent:**

> [Borrador, aún sin verificar]
> 
> Gracias por confirmar. Esto es lo que muestran los datos para el banano en Piura, y lo que hicieron otras organizaciones con problemas de agua parecidos.
> 
> 1. En su zona, la lluvia de las dos últimas temporadas fue 31% menor que el promedio de 10 años. El estrés hídrico ya es extremadamente alto, y la proyección para 2030 sigue igual. Es decir, la falta de agua no parece ser solo de este año.
>    Fuentes: CHIRPS v2.0 rainfall (SYNTHETIC STAND-IN); WRI Aqueduct 4.0 (SYNTHETIC STAND-IN)
>    Normas relacionadas: APS (ILLUSTRATIVE PLACEHOLDER) APS-DEMO-2.1; APS (ILLUSTRATIVE PLACEHOLDER) APS-DEMO-4.1
> 2. En la encuesta de 2025 de su cooperativa respondieron 99 socios. El agua fue el problema más mencionado, y el 54% dijo que su rendimiento bajó. Antes ya probaron regar a mano, y el comité de agua pidió apoyo a la municipalidad.
>    Fuentes: Encuesta 2025; Conversación anterior
>    Normas relacionadas: APS (ILLUSTRATIVE PLACEHOLDER) APS-DEMO-2.1
> 3. En 2022 ustedes plantaron árboles de sombra nativos para reducir la pérdida de humedad del suelo. El proyecto se terminó, pero mantenerlo costó más de lo planeado. Esto puede servir para calcular los costos de cualquier nueva medida.
>    Fuentes: Proyecto Premium: Shade-tree planting
>    Normas relacionadas: APS (ILLUSTRATIVE PLACEHOLDER) APS-DEMO-4.1; APS (ILLUSTRATIVE PLACEHOLDER) APS-DEMO-2.2
> 4. Plantación La Esperanza, en Colombia, también produce banano. En 2022 instaló tanques para captar agua de lluvia en casas y viveros, para pasar los meses secos. Invirtió 31.000 dólares y reporta menos días de cosecha perdidos. Son tanques repartidos entre muchos puntos, distinto a un solo reservorio, pero también dependen de la lluvia, que en su zona ha bajado.
>    Fuentes: Plantación La Esperanza (Colombia); CHIRPS v2.0 rainfall (SYNTHETIC STAND-IN)
>    Normas relacionadas: APS (ILLUSTRATIVE PLACEHOLDER) APS-DEMO-2.1
> 5. La Cooperativa Cumbre Azul, en Honduras, produce café. En 2022 instaló tanques de agua de lluvia en casas y viveros, con 43.000 dólares. Cerca de dos tercios de sus socios los adoptaron.
>    Fuentes: Cooperativa Cumbre Azul (Honduras)
>    Normas relacionadas: APS (ILLUSTRATIVE PLACEHOLDER) APS-DEMO-2.1
> 
> Lo que los datos no cubren:
> - No tenemos datos sobre por qué no alcanzó el reservorio pequeño, ni sobre qué tamaño haría falta para 360 familias.
> - No encontramos casos de pozos, riego por goteo u otras fuentes de agua para banano en zonas secas como Piura.
> - No sabemos qué respondió la municipalidad cuando el comité de agua pidió apoyo.
> - Los datos regionales de lluvia y estrés hídrico no indican fechas exactas.
> 
> Ustedes conocen mejor su quebrada y a sus socios. La decisión de qué hacer con esta información es de la cooperativa.

Memory after this turn: stage `drafted` · understanding v2 · missing nothing · confirmed True · evidence 14 · notes 0 · log 21 events · staged facts [('member_count', '360')] · PII []

Model runs: playback[confirm_understanding] → retrieve[get_producer_record, get_regional_context, search_peer_examples, retrieve_standards] → draft[submit_guidance]

### Commit and review

- approve `member_count` = `360`, supported by: "ya somos 360 familias"
- approve the episode (0 notes, PII: none)

### Checks

- PASS: the approved entity type still applies
- PASS: the newest reviewed member count applies
- PASS: the older value is kept and marked as superseded
- PASS: both approved episodes are available to later exchanges
- PASS: the registered source record is unchanged
- PASS: the registered member count is unchanged
- PASS: the location scope is unchanged
- PASS: discarding an exchange deletes its state and whole log
- PASS: the reviewed episode survives the discard

## Result

29 of 29 checks passed.
Tokens: 73,233 input, 9,344 output.
