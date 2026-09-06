import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.file.Path;

import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.stream.XMLEventReader;
import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.events.XMLEvent;

import org.w3c.dom.Document;
import org.w3c.dom.NodeList;
import org.xml.sax.helpers.DefaultHandler;

/**
 * THE DELIBERATELY VULNERABLE COPY. Do not reuse any of it.
 *
 * Both methods read an order document and return the customer name. Neither
 * touches a security setting, which is the entire point: this is what the
 * factory hands you when you call newInstance() and start parsing. Nothing here
 * looks wrong, and nothing here is unusual.
 */
public final class VulnerableIntake {

    private VulnerableIntake() {
    }

    /** DOM. javax.xml.parsers.DocumentBuilderFactory at its defaults. */
    public static String customerViaDom(Path xml) throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        DocumentBuilder builder = factory.newDocumentBuilder();
        // Rethrow instead of letting the default handler print to stderr; this is
        // ordinary practice and changes nothing about what gets resolved.
        builder.setErrorHandler(new DefaultHandler());
        Document document = builder.parse(xml.toFile());
        NodeList matches = document.getElementsByTagName("customer");
        if (matches.getLength() == 0) {
            throw new IllegalArgumentException("no <customer> element in " + xml);
        }
        return matches.item(0).getTextContent().trim();
    }

    /** StAX. javax.xml.stream.XMLInputFactory at its defaults. */
    public static String customerViaStax(Path xml) throws Exception {
        XMLInputFactory factory = XMLInputFactory.newInstance();
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
