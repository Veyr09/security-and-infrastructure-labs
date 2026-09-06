/* hdrparse - read a "Key: value" header block and print a summary.
 *
 * This is the fixed copy. Same program, same output for well-formed input as
 * ../vulnerable/hdrparse.c, with all five defects closed.
 *
 * The rule applied throughout: a value that does not fit is an error the
 * caller is told about, not something quietly truncated. Truncating turns a
 * loud failure into a wrong answer, and a wrong answer in a parser is how a
 * name ends up half-written into a database three steps later.
 */
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_LINE 512
#define NAME_LEN 32
#define TAG_LEN 16
#define MAX_ROLES 1024

struct header {
    char *name;
    char *tag;
    char **roles;
    int roles_declared;
    int roles_seen;
    char *note;
    char *first_note;
};

static char *trim(char *s)
{
    while (*s == ' ' || *s == '\t')
        s++;
    char *end = s + strlen(s);
    while (end > s && (end[-1] == '\n' || end[-1] == '\r' || end[-1] == ' ' || end[-1] == '\t'))
        *--end = '\0';
    return s;
}

static void fail(const char *fmt, ...) __attribute__((format(printf, 1, 2), noreturn));

static void fail(const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    fputs("hdrparse: ", stderr);
    vfprintf(stderr, fmt, args);
    fputc('\n', stderr);
    va_end(args);
    exit(1);
}

static void *xmalloc(size_t n)
{
    void *p = malloc(n);
    if (p == NULL)
        fail("out of memory allocating %zu bytes", n);
    return p;
}

static char *xstrdup(const char *s)
{
    char *copy = strdup(s);
    if (copy == NULL)
        fail("out of memory copying a %zu-byte value", strlen(s));
    return copy;
}

/* Copy into a fixed buffer, or fail saying by how much it did not fit. */
static void copy_bounded(char *dst, size_t cap, const char *field, const char *value)
{
    size_t n = strlen(value);
    if (n >= cap)
        fail("%s is %zu characters, limit is %zu", field, n, cap - 1);
    memcpy(dst, value, n + 1);
}

/* strtol with every failure mode the man page lists actually checked. */
static int parse_count(const char *field, const char *value)
{
    errno = 0;
    char *end = NULL;
    long parsed = strtol(value, &end, 10);
    if (end == value || *end != '\0')
        fail("%s is not a number: \"%s\"", field, value);
    if (errno == ERANGE || parsed < 0 || parsed > MAX_ROLES)
        fail("%s is %s, must be between 0 and %d", field, value, MAX_ROLES);
    return (int)parsed;
}

int main(int argc, char **argv)
{
    FILE *in = stdin;
    if (argc > 1 && (in = fopen(argv[1], "r")) == NULL) {
        perror(argv[1]);
        return 2;
    }

    struct header h;
    memset(&h, 0, sizeof h);
    h.name = xmalloc(NAME_LEN);
    h.tag = xmalloc(TAG_LEN);
    memcpy(h.name, "anonymous", sizeof "anonymous");
    memcpy(h.tag, "none", sizeof "none");

    char line[MAX_LINE];
    while (fgets(line, sizeof line, in)) {
        char *colon = strchr(line, ':');
        if (colon == NULL)
            continue;
        *colon = '\0';
        char *key = trim(line);
        char *value = trim(colon + 1);

        if (strcmp(key, "Name") == 0) {
            copy_bounded(h.name, NAME_LEN, "Name", value);
        } else if (strcmp(key, "Tag") == 0) {
            copy_bounded(h.tag, TAG_LEN, "Tag", value);
        } else if (strcmp(key, "Roles") == 0) {
            h.roles_declared = parse_count("Roles", value);
            for (int i = 0; i < h.roles_seen; i++)
                free(h.roles[i]);
            free(h.roles);
            h.roles_seen = 0;
            /* One extra slot so a count of 0 is still a valid allocation. */
            h.roles = xmalloc(((size_t)h.roles_declared + 1) * sizeof *h.roles);
        } else if (strcmp(key, "Role") == 0) {
            if (h.roles == NULL)
                fail("a Role line appeared before the Roles count");
            if (h.roles_seen >= h.roles_declared)
                fail("more Role lines than the Roles count of %d", h.roles_declared);
            h.roles[h.roles_seen++] = xstrdup(value);
        } else if (strcmp(key, "Note") == 0) {
            free(h.note);
            h.note = xstrdup(value);
            /* Own the copy rather than aliasing one that gets freed later. */
            if (h.first_note == NULL)
                h.first_note = xstrdup(value);
        }
    }

    printf("name  : %s\n", h.name);
    printf("tag   : %s\n", h.tag);
    printf("roles : %d declared, %d seen\n", h.roles_declared, h.roles_seen);
    for (int i = 0; i < h.roles_seen; i++)
        printf("        - %s\n", h.roles[i]);
    if (h.note != NULL)
        printf("note  : %s\n", h.note);
    if (h.first_note != NULL)
        printf("first : %s (%zu characters)\n", h.first_note, strlen(h.first_note));

    for (int i = 0; i < h.roles_seen; i++)
        free(h.roles[i]);
    free(h.roles);
    free(h.first_note);
    free(h.note);
    free(h.tag);
    free(h.name);
    if (in != stdin)
        fclose(in);
    return 0;
}
