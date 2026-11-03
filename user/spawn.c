#include <stdio.h>
#include <unistd.h>
#include <wait.h>

#define TOKEN "b4e76741-a67d-4f87-8212-61f6290cf175"

int spawn(const char *path);

int spawn(const char *path)
{
    // Call syscall with number 300
    return syscall(300, path);
}

int main(int argc, char *argv[])
{
    // Disable buffer in STDOUT
    setvbuf(stdout, NULL, _IONBF, 0);

    printf("Running spawn user mode program\n");

    int spawn_pid = getpid();
    int current_pid = spawn_pid;
    for (int i = 0; i < 10; i++)
    {
        int pid = spawn("spawn_test");
        if (current_pid + 1 != pid)
        {
            return 1;
        }
        current_pid += 1;
    }

    current_pid = spawn_pid;
    for (int i = 0; i < 10; i++)
    {
        int wait_status;
        int wait_pid = wait(&wait_status);
        if (current_pid + 1 != wait_pid)
        {
            return 1;
        }
        if (wait_status != 100)
        {
            return 1;
        }
        current_pid += 1;
    }
    printf("Spawn test passed!\n");

    printf("Token: %s\n", TOKEN);

    return 0;
}