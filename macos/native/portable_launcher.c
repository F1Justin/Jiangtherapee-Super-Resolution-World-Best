#include <mach-o/dyld.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char executable[PATH_MAX], resolved[PATH_MAX], resources[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) || !realpath(executable, resolved)) {
        perror("JSR launcher path"); return 1;
    }
    char *slash = strrchr(resolved, '/');
    if (!slash) return 1;
    *slash = '\0';
    snprintf(executable, sizeof(executable), "%s/../Resources", resolved);
    if (!realpath(executable, resources)) { perror("JSR resources"); return 1; }
    char python[PATH_MAX], script[PATH_MAX], value[PATH_MAX];
    snprintf(python, sizeof(python), "%s/runtime/bin/python3.10", resources);
    snprintf(script, sizeof(script), "%s/engine/portable_cli.pyc", resources);
    const char *remove[] = {"PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE",
                           "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"};
    for (size_t i = 0; i < sizeof(remove)/sizeof(remove[0]); ++i) unsetenv(remove[i]);
    snprintf(value, sizeof(value), "%s/runtime", resources); setenv("PYTHONHOME", value, 1);
    setenv("PYTHONNOUSERSITE", "1", 1); setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
    snprintf(value, sizeof(value), "%s/tools:/usr/bin:/bin:/usr/sbin:/sbin", resources); setenv("PATH", value, 1);
    snprintf(value, sizeof(value), "%s/runtime/lib/tcl8.6", resources); setenv("TCL_LIBRARY", value, 1);
    snprintf(value, sizeof(value), "%s/runtime/lib/tk8.6", resources); setenv("TK_LIBRARY", value, 1);
    setenv("JSR_PORTABLE", "1", 1);
    const char *name = strrchr(argv[0], '/'); name = name ? name + 1 : argv[0];
    int gui = !strcmp(name, "JSR");
    char **args = calloc((size_t)argc + 5, sizeof(char *));
    if (!args) return 1;
    args[0] = python; args[1] = "-s"; args[2] = script;
    if (gui) args[3] = "gui";
    else for (int i = 1; i < argc; ++i) args[i + 2] = argv[i];
    execv(python, args);
    perror("JSR Python runtime"); free(args); return 1;
}
