/* hdrparse - read a "Key: value" header block and print a summary.
 *
 * THIS IS THE DELIBERATELY VULNERABLE COPY. Do not reuse any of it.
 *
 * Five defects are planted here, each marked with its CWE. They are the ones
 * that actually turn up in C that parses input someone else wrote: an
 * unbounded copy, an off-by-one, a trusted length field, a stale pointer, and
 * a format string. ../fixed/hdrparse.c is the same program with all five
 * closed, and the tests run both against the same inputs.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_LINE 512
#define NAME_LEN 32
#define TAG_LEN 16

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

int main(int argc, char **argv)
{
    FILE *in = stdin;
    if (argc > 1 && (in = fopen(argv[1], "r")) == NULL) {
        perror(argv[1]);
        return 2;
    }

    struct header h;
    memset(&h, 0, sizeof h);
    h.name = malloc(NAME_LEN);
    h.tag = malloc(TAG_LEN);
    strcpy(h.name, "anonymous");
    strcpy(h.tag, "none");

    char line[MAX_LINE];
    while (fgets(line, sizeof line, in)) {
        char *colon = strchr(line, ':');
        if (colon == NULL)
            continue;
        *colon = '\0';
        char *key = trim(line);
        char *value = trim(colon + 1);

        if (strcmp(key, "Name") == 0) {
            /* CWE-787: the value is copied into a 32-byte buffer without
             * checking that it fits. */
            strcpy(h.name, value);
        } else if (strcmp(key, "Tag") == 0) {
            size_t n = strlen(value);
            if (n > TAG_LEN) /* CWE-193: the limit is TAG_LEN - 1, because of the terminator */
                n = TAG_LEN;
            memcpy(h.tag, value, n);
            h.tag[n] = '\0'; /* one byte past the end when n == TAG_LEN */
        } else if (strcmp(key, "Roles") == 0) {
            h.roles_declared = atoi(value);
            free(h.roles);
            h.roles = malloc((size_t)h.roles_declared * sizeof *h.roles);
        } else if (strcmp(key, "Role") == 0) {
            /* CWE-122: the count in the Roles header is trusted, and the Role
             * lines that follow are never counted against it. */
            h.roles[h.roles_seen++] = strdup(value);
        } else if (strcmp(key, "Note") == 0) {
            free(h.note);
            h.note = strdup(value);
            if (h.first_note == NULL)
                h.first_note = h.note; /* CWE-416: dangles as soon as a second Note arrives */
        }
    }

    printf("name  : %s\n", h.name);
    printf("tag   : %s\n", h.tag);
    printf("roles : %d declared, %d seen\n", h.roles_declared, h.roles_seen);
    for (int i = 0; i < h.roles_seen; i++)
        printf("        - %s\n", h.roles[i]);
    if (h.note != NULL) {
        fputs("note  : ", stdout);
        printf(h.note); /* CWE-134: the value is used as the format string */
        putchar('\n');
    }
    if (h.first_note != NULL)
        printf("first : %s (%zu characters)\n", h.first_note, strlen(h.first_note));

    for (int i = 0; i < h.roles_seen; i++)
        free(h.roles[i]);
    free(h.roles);
    free(h.note);
    free(h.tag);
    free(h.name);
    if (in != stdin)
        fclose(in);
    return 0;
}
