# XXE in Java: what the default parser does, and the settings that stop it

Two classes read the same order document and return the customer name.
`VulnerableIntake` uses `DocumentBuilderFactory` and `XMLInputFactory` exactly
as `newInstance()` hands them over. `SecureIntake` is the same code with the
factories hardened. The suite runs the same four documents through both.

The vulnerable copy is not doing anything odd. It has no unusual configuration,
no deprecated call, and nothing a reviewer would flag on sight. That is the
whole problem with XXE in Java: **the insecure behaviour is the default**, and
the code that has it looks exactly like code that does not.

## Run it

```
bash run_tests.sh
```

The JDK is the only dependency — no Maven, no Gradle, no JUnit. Set `JAVA_HOME`
to pick a particular JDK.

Measured on Temurin **JDK 21.0.12.1**: **16 assertions, all passing.** Captured
output is in `sample/test-run.txt`.

## What actually happens

| document | vulnerable/DOM | vulnerable/StAX | secure/DOM | secure/StAX |
|---|---|---|---|---|
| `good.xml` | `Acme Ltd` | `Acme Ltd` | `Acme Ltd` | `Acme Ltd` |
| `xxe-file.xml` | **discloses the file** | **discloses the file** | refuses | refuses |
| `xxe-external-dtd.xml` | **fetches the DTD, discloses** | **fetches the DTD, discloses** | refuses | refuses |
| `billion-laughs.xml` | refused by the JDK | refused by the JDK | refuses | refuses |

Both default parsers hand back 82 characters of `cases/secret.txt` in place of
the customer name. The document that does it is five lines:

```xml
<!DOCTYPE order [
  <!ENTITY leak SYSTEM "secret.txt">
]>
<order id="1042">
  <customer>&leak;</customer>
```

`xxe-external-dtd.xml` is the same attack with the entity moved into a separate
`leak.dtd` that the parser goes and fetches. It is in the corpus because the
two are stopped by *different* settings, and a fix that only closes the first
leaves a working hole.

## The part worth knowing: Java is not defenceless, which is why people assume it is safe

`billion-laughs.xml` expands to roughly ten million characters. **Both default
parsers refuse it**, with `JAXP00010001: The parser has encountered more than
"64000" entity expansions in this document; this is the limit imposed by the
JDK.`

So the JDK does ship with a defence against entity-expansion denial of service,
switched on, needing no configuration. It ships with **no** equivalent defence
against entity-driven file disclosure. Someone who tests the famous attack, sees
it blocked, and concludes the parser is safe has drawn exactly the wrong
conclusion from a true observation. That asymmetry is the reason this piece
exists.

## The two APIs do not share a fix

The DOM hardening is a list of SAX feature strings:

```java
factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
factory.setFeature("http://xml.org/sax/features/external-general-entities", false);
factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
factory.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false);
factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
factory.setXIncludeAware(false);
factory.setExpandEntityReferences(false);
```

`XMLInputFactory` does not recognise any of those names, and handing them to it
throws. StAX has its own two:

```java
factory.setProperty(XMLInputFactory.SUPPORT_DTD, false);
factory.setProperty(XMLInputFactory.IS_SUPPORTING_EXTERNAL_ENTITIES, false);
```

This matters in real code because a service usually parses XML in more than one
place. Hardening the `DocumentBuilderFactory` in the request handler and leaving
an `XMLInputFactory` in the batch importer fixes the path that was audited and
not the one that was not. The suite covers both deliberately.

The first DOM line does the real work: with no DOCTYPE accepted there is no
entity to resolve, so every other setting is redundant. The rest stay because
someone will eventually need DOCTYPE back for a schema, flip that one line, and
not read the remaining six.

## How the refusals differ, and why the test checks the reason

The hardened parsers fail in two different ways, and both are asserted by
message rather than by exit status:

- **DOM** throws `SAXParseException: DOCTYPE is disallowed when the feature
  "http://apache.org/xml/features/disallow-doctype-decl" set to true.` — the
  document is rejected at the DOCTYPE, before any entity exists.
- **StAX** throws `XMLStreamException: The entity "leak" was referenced, but not
  declared.` — the DOCTYPE is skipped, so the reference has nothing behind it.

Every `refuses` assertion also checks that the file contents are **not** in the
exception message. A parser that blocks the read and then prints what it would
have read has not fixed anything, and that is a real failure mode in code that
logs the offending document.

## Files

- `src/VulnerableIntake.java` — DOM and StAX readers at factory defaults
- `src/SecureIntake.java` — the same two, hardened, with the reasoning in comments
- `src/Harness.java` — 16 assertions, no test framework
- `src/Probe.java` — prints what each parser does with each document; how the
  expectations above were established rather than guessed
- `cases/` — the four documents, plus `leak.dtd` and the `secret.txt` fixture
- `run_tests.sh`, `sample/test-run.txt`

## Honest scope

Built for this portfolio, not client work. `cases/secret.txt` is a fixture and
contains no real credential. Nothing here was run against anyone else's system.
The behaviour described is the JDK's own XML implementation at version 21.0.12.1;
a different JDK, or a third-party parser such as Woodstox, may differ, which is
itself a reason to run the probe rather than trust a table.
