import java.nio.file.Path;
import java.nio.file.Paths;

/** Prints what each parser actually does with each case. Used to write the tests. */
public final class Probe {

    private static final String[] CASES = {
        "good.xml", "xxe-file.xml", "xxe-external-dtd.xml", "billion-laughs.xml"
    };

    public static void main(String[] args) {
        Path dir = Paths.get(args.length > 0 ? args[0] : "cases");
        for (String name : CASES) {
            Path xml = dir.resolve(name);
            report(name, "vulnerable/DOM", () -> VulnerableIntake.customerViaDom(xml));
            report(name, "secure/DOM", () -> SecureIntake.customerViaDom(xml));
            report(name, "vulnerable/StAX", () -> VulnerableIntake.customerViaStax(xml));
            report(name, "secure/StAX", () -> SecureIntake.customerViaStax(xml));
            System.out.println();
        }
    }

    interface Call {
        String run() throws Exception;
    }

    private static void report(String name, String label, Call call) {
        String outcome;
        try {
            String value = call.run();
            String shown = value.length() > 60 ? value.substring(0, 60) + "... (" + value.length() + " chars)" : value;
            outcome = "returned [" + shown.replace("\n", "\\n") + "]";
        } catch (Throwable problem) {
            String message = problem.getMessage();
            if (message != null && message.length() > 90) {
                message = message.substring(0, 90) + "...";
            }
            outcome = "threw " + problem.getClass().getSimpleName() + ": " + message;
        }
        System.out.printf("%-22s %-18s %s%n", name, label, outcome);
    }
}
