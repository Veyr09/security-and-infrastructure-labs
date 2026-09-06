import java.nio.file.Path;
import java.nio.file.Paths;

/**
 * Runs the same documents through the vulnerable and the hardened readers.
 *
 * Every XXE case asserts both halves: that the default parser really does
 * disclose the file, and that the hardened one refuses. Asserting only the
 * second would not show the setting was doing anything.
 *
 * No test framework, so there is nothing to install: javac src/*.java, then
 * java -cp build Harness cases.
 */
public final class Harness {

    /** A string from cases/secret.txt. If it reaches the caller, the file was read. */
    private static final String SECRET_MARKER = "db.password";

    private static int passed;
    private static int failed;

    public static void main(String[] args) {
        Path dir = Paths.get(args.length > 0 ? args[0] : "cases");

        section("a well-formed order, which both readers must still accept");
        returns("vulnerable/DOM  accepts good.xml", () -> VulnerableIntake.customerViaDom(dir.resolve("good.xml")), "Acme Ltd");
        returns("secure/DOM      accepts good.xml", () -> SecureIntake.customerViaDom(dir.resolve("good.xml")), "Acme Ltd");
        returns("vulnerable/StAX accepts good.xml", () -> VulnerableIntake.customerViaStax(dir.resolve("good.xml")), "Acme Ltd");
        returns("secure/StAX     accepts good.xml", () -> SecureIntake.customerViaStax(dir.resolve("good.xml")), "Acme Ltd");

        section("CWE-611, an inline entity reading a local file");
        leaks("vulnerable/DOM  discloses secret.txt", () -> VulnerableIntake.customerViaDom(dir.resolve("xxe-file.xml")));
        refuses("secure/DOM      refuses the DOCTYPE", () -> SecureIntake.customerViaDom(dir.resolve("xxe-file.xml")), "disallow-doctype-decl");
        leaks("vulnerable/StAX discloses secret.txt", () -> VulnerableIntake.customerViaStax(dir.resolve("xxe-file.xml")));
        refuses("secure/StAX     leaves the entity undeclared", () -> SecureIntake.customerViaStax(dir.resolve("xxe-file.xml")), "was referenced, but not declared");

        section("CWE-611, the entity hidden in an external DTD");
        leaks("vulnerable/DOM  fetches leak.dtd and discloses", () -> VulnerableIntake.customerViaDom(dir.resolve("xxe-external-dtd.xml")));
        refuses("secure/DOM      refuses the DOCTYPE", () -> SecureIntake.customerViaDom(dir.resolve("xxe-external-dtd.xml")), "disallow-doctype-decl");
        leaks("vulnerable/StAX fetches leak.dtd and discloses", () -> VulnerableIntake.customerViaStax(dir.resolve("xxe-external-dtd.xml")));
        refuses("secure/StAX     leaves the entity undeclared", () -> SecureIntake.customerViaStax(dir.resolve("xxe-external-dtd.xml")), "was referenced, but not declared");

        section("CWE-776, entity expansion, which the JDK already limits by itself");
        refuses("vulnerable/DOM  stopped by the JDK's own 64000 limit", () -> VulnerableIntake.customerViaDom(dir.resolve("billion-laughs.xml")), "JAXP00010001");
        refuses("vulnerable/StAX stopped by the JDK's own 64000 limit", () -> VulnerableIntake.customerViaStax(dir.resolve("billion-laughs.xml")), "JAXP00010001");
        refuses("secure/DOM      refuses earlier, at the DOCTYPE", () -> SecureIntake.customerViaDom(dir.resolve("billion-laughs.xml")), "disallow-doctype-decl");
        refuses("secure/StAX     leaves the entity undeclared", () -> SecureIntake.customerViaStax(dir.resolve("billion-laughs.xml")), "was referenced, but not declared");

        System.out.printf("%n%d passed, %d failed%n", passed, failed);
        System.exit(failed == 0 ? 0 : 1);
    }

    interface Call {
        String run() throws Exception;
    }

    private static void section(String title) {
        System.out.printf("%n%s%n", title);
    }

    /** The call must succeed and return exactly this. */
    private static void returns(String label, Call call, String expected) {
        try {
            String actual = call.run();
            if (expected.equals(actual)) {
                ok(label);
            } else {
                bad(label, "returned \"" + actual + "\", expected \"" + expected + "\"");
            }
        } catch (Throwable problem) {
            bad(label, "threw " + problem.getClass().getSimpleName() + ": " + firstLine(problem.getMessage()));
        }
    }

    /** The call must succeed AND hand back the contents of the file it should never have read. */
    private static void leaks(String label, Call call) {
        try {
            String actual = call.run();
            if (actual.contains(SECRET_MARKER)) {
                ok(label + " (" + actual.length() + " chars of it)");
            } else {
                bad(label, "returned \"" + firstLine(actual) + "\" with no sign of the file");
            }
        } catch (Throwable problem) {
            bad(label, "threw " + problem.getClass().getSimpleName() + ": " + firstLine(problem.getMessage()));
        }
    }

    /** The call must fail, for the stated reason, without the file contents in the message. */
    private static void refuses(String label, Call call, String expectedReason) {
        try {
            String actual = call.run();
            bad(label, "returned \"" + firstLine(actual) + "\" instead of refusing");
        } catch (Throwable problem) {
            String message = String.valueOf(problem.getMessage());
            if (message.contains(SECRET_MARKER)) {
                bad(label, "refused, but the file contents were in the error message");
            } else if (message.contains(expectedReason)) {
                ok(label);
            } else {
                bad(label, "refused for the wrong reason: " + firstLine(message));
            }
        }
    }

    private static String firstLine(String text) {
        if (text == null) {
            return "(no message)";
        }
        String line = text.split("\n", 2)[0].trim();
        return line.length() > 100 ? line.substring(0, 100) + "..." : line;
    }

    private static void ok(String label) {
        System.out.println("  ok   " + label);
        passed++;
    }

    private static void bad(String label, String detail) {
        System.out.println("  FAIL " + label);
        System.out.println("       " + detail);
        failed++;
    }
}
