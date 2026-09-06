import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.file.Path;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.stream.XMLEventReader;
import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.events.XMLEvent;

import org.w3c.dom.Document;
import org.w3c.dom.NodeList;
import org.xml.sax.helpers.DefaultHandler;

/**
 * The same two readers, hardened.
 *
 * The settings are not interchangeable between the two APIs, which is the part
 * that catches people out: the DOM fix is a list of SAX feature strings, and
 * pasting it at an XMLInputFactory does nothing because StAX does not know
 * those names. Each factory has to be hardened in its own vocabulary.
 */
public final class SecureIntake {

    /** Apache/Xerces feature names, which the JDK's built-in parser also honours. */
    private static final String DISALLOW_DOCTYPE = "http://apache.org/xml/features/disallow-doctype-decl";
    private static final String EXTERNAL_GENERAL_ENTITIES = "http://xml.org/sax/features/external-general-entities";
    private static final String EXTERNAL_PARAMETER_ENTITIES = "http://xml.org/sax/features/external-parameter-entities";
    private static final String LOAD_EXTERNAL_DTD = "http://apache.org/xml/features/nonvalidating/load-external-dtd";

    private SecureIntake() {
    }

    public static String customerViaDom(Path xml) throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();

        // The one that does the work: no DOCTYPE at all means no entity to
        // resolve, so every variant below is moot. Refuse the document rather
        // than trying to parse it safely.
        factory.setFeature(DISALLOW_DOCTYPE, true);

        // Belt and braces, for the day someone needs DOCTYPE back for a schema
        // and flips the line above without reading the rest of this method.
        factory.setFeature(EXTERNAL_GENERAL_ENTITIES, false);
        factory.setFeature(EXTERNAL_PARAMETER_ENTITIES, false);
        factory.setFeature(LOAD_EXTERNAL_DTD, false);
        factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        factory.setXIncludeAware(false);
        factory.setExpandEntityReferences(false);

        DocumentBuilder builder = factory.newDocumentBuilder();
        builder.setErrorHandler(new DefaultHandler());
        Document document = builder.parse(xml.toFile());
        NodeList matches = document.getElementsByTagName("customer");
        if (matches.getLength() == 0) {
            throw new IllegalArgumentException("no <customer> element in " + xml);
        }
        return matches.item(0).getTextContent().trim();
    }

    public static String customerViaStax(Path xml) throws Exception {
        XMLInputFactory factory = XMLInputFactory.newInstance();

        // StAX speaks a different language. SUPPORT_DTD false is the equivalent
        // of disallow-doctype-decl; the SAX feature strings above are not
        // recognised here and setting them throws.
        factory.setProperty(XMLInputFactory.SUPPORT_DTD, false);
        factory.setProperty(XMLInputFactory.IS_SUPPORTING_EXTERNAL_ENTITIES, false);

        try (InputStream in = new FileInputStream(xml.toFile())) {
            XMLEventReader reader = factory.createXMLEventReader(xml.toUri().toString(), in);
            StringBuilder text = new StringBuilder();
            boolean inCustomer = false;
            while (reader.hasNext()) {
                XMLEvent event = reader.nextEvent();
                if (event.isStartElement()
                        && "customer".equals(event.asStartElement().getName().getLocalPart())) {
                    inCustomer = true;
                } else if (event.isEndElement()
                        && "customer".equals(event.asEndElement().getName().getLocalPart())) {
                    inCustomer = false;
                } else if (inCustomer && event.isCharacters()) {
                    text.append(event.asCharacters().getData());
                }
            }
            return text.toString().trim();
        }
    }
}
