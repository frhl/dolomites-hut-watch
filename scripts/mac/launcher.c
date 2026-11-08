/*
 * "Dolomites Hut Watch": tiny launcher so the hourly Mac check has a recognisable name.
 * macOS lists background items (System Settings > Login Items) and processes (Activity
 * Monitor) by executable name; a plain shell script would show up as "bash". This binary
 * runs scripts/local_check.sh as a child and waits for it, so "Dolomites Hut Watch" is the
 * process you see while a check runs (with bash/python children for ~10 seconds).
 *
 * Usage: "Dolomites Hut Watch" [path/to/local_check.sh]   (default baked in at build time)
 */
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>

#ifndef HUTWATCH_SCRIPT
#define HUTWATCH_SCRIPT ""
#endif

extern char **environ;

int main(int argc, char **argv) {
    const char *script = argc > 1 ? argv[1] : HUTWATCH_SCRIPT;
    if (!script[0]) {
        fprintf(stderr, "usage: %s path/to/local_check.sh\n", argv[0]);
        return 2;
    }
    char *child_argv[] = {"/bin/bash", (char *)script, NULL};
    pid_t pid;
    int status;
    if (posix_spawn(&pid, "/bin/bash", NULL, NULL, child_argv, environ) != 0) {
        perror("posix_spawn");
        return 1;
    }
    if (waitpid(pid, &status, 0) < 0) {
        perror("waitpid");
        return 1;
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
