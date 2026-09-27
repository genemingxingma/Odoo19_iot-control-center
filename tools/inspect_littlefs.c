/* Read-only inspection of an extracted ESP8266 LittleFS backup. */
#include "lfs.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int read_block(const struct lfs_config *c, lfs_block_t block,
                      lfs_off_t offset, void *buffer, lfs_size_t size) {
    FILE *image = c->context;
    if (fseek(image, (long)block * c->block_size + offset, SEEK_SET)) return LFS_ERR_IO;
    return fread(buffer, 1, size, image) == size ? 0 : LFS_ERR_IO;
}
static int no_prog(const struct lfs_config *c, lfs_block_t b, lfs_off_t o,
                   const void *p, lfs_size_t s) { (void)c; (void)b; (void)o; (void)p; (void)s; return LFS_ERR_IO; }
static int no_erase(const struct lfs_config *c, lfs_block_t b) { (void)c; (void)b; return LFS_ERR_IO; }
static int no_sync(const struct lfs_config *c) { (void)c; return 0; }
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    FILE *image = fopen(argv[1], "rb"); if (!image) return 3;
    struct lfs_config config = {0};
    config.context = image; config.read = read_block; config.prog = no_prog;
    config.erase = no_erase; config.sync = no_sync;
    config.read_size = 256; config.prog_size = 256; config.block_size = 8192;
    config.block_count = 125; config.block_cycles = 1000;
    config.cache_size = 256; config.lookahead_size = 32;
    lfs_t filesystem;
    int error = lfs_mount(&filesystem, &config);
    if (error) { fclose(image); return 4; }
    lfs_ssize_t used = lfs_fs_size(&filesystem);
    unsigned observations = 0, critical = 0;
    lfs_dir_t directory; struct lfs_info info;
    if (!lfs_dir_open(&filesystem, &directory, "/events")) {
        while (lfs_dir_read(&filesystem, &directory, &info) > 0) {
            if (info.type != LFS_TYPE_REG) continue;
            if (strstr(info.name, ".obs.json")) ++observations; else ++critical;
        }
        lfs_dir_close(&filesystem, &directory);
    }
    printf("{\"total_blocks\":125,\"used_blocks\":%ld,\"block_bytes\":8192,\"observations\":%u,\"critical_events\":%u}\n",
        (long)used, observations, critical);
    lfs_unmount(&filesystem); fclose(image); return used < 0 ? 5 : 0;
}
