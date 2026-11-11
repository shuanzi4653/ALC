/*
 * edge_x86_main.c —— Plan B 用的 x86 宿主程序：把**同一份** edge_infer.c 编成本机可执行，
 * 用命令行喂 cases.csv，逐行输出与固件完全相同的文本协议。
 *
 * 为什么要有这个文件
 * ------------------
 * 比赛材料里说的是"端侧与云端同源对拍"。如果 ESP32 工具链装不上、板子没到、CH340 没枚举，
 * 这条结论不能凭"代码看着一样"来写。用 MSVC/MinGW 把同一份 edge_infer.c 编成 x86 可执行，
 * 在相同的 float32 语义下逐条比对，能把"代码等价"变成"实测等价"，
 * 对外表述写成"同一份 C 代码在等价编译目标上验证"，这是真话，不是退让。
 *
 * 输出协议（与 edge_esp32.ino 一致，pair_check.py 只认这一个协议）
 * -------------------------------------------------------------
 *   # MODEL <format> <version> fp=<指纹>        自检头
 *   # <edge_self_check 的文本>                   含 trees/features/nodes/leaves/bytes/checks
 *   # READY                                     之后开始逐行应答
 *   RES <seq> <p:6位小数> <pc:6位小数> <us>      每个用例一行
 *   # SUMMARY N=<n> US_MIN=<..> US_MAX=<..> US_MEAN=<..>
 *
 * 用法：
 *   edge_x86.exe cases.csv
 *   edge_x86.exe cases.csv > edge_x86_log.txt
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "edge_infer.h"

#ifdef _WIN32
#include <windows.h>
static double edge_now_us(void) {
    static LARGE_INTEGER frequency;
    static int initialized = 0;
    LARGE_INTEGER counter;
    if (!initialized) {
        QueryPerformanceFrequency(&frequency);
        initialized = 1;
    }
    QueryPerformanceCounter(&counter);
    return (double)counter.QuadPart * 1000000.0 / (double)frequency.QuadPart;
}
#else
#include <time.h>
static double edge_now_us(void) {
    struct timespec moment;
    clock_gettime(CLOCK_MONOTONIC, &moment);
    return (double)moment.tv_sec * 1000000.0 + (double)moment.tv_nsec / 1000.0;
}
#endif

#define EDGE_LINE_MAX 4096

/** 一行里读 26 个数；返回读到的个数（不足说明这行不完整，调用方会跳过并记账）。 */
static int parse_vector(const char *line, float x[EDGE_FEATURE_COUNT]) {
    const char *cursor = line;
    int count = 0;
    while (count < EDGE_FEATURE_COUNT) {
        char *end = NULL;
        double value;
        while (*cursor == ' ' || *cursor == '\t' || *cursor == ',' || *cursor == ';') {
            ++cursor;
        }
        if (*cursor == '\0' || *cursor == '\n' || *cursor == '\r' || *cursor == '#') {
            break;
        }
        value = strtod(cursor, &end);
        if (end == cursor) {
            break;
        }
        /* 显式转 float：cases.csv 里的每个数都是 float32 精确可表示的十进制串，
         * 这一步不引入新的量化误差（gen_cases.py 里有断言保证）。 */
        x[count++] = (float)value;
        cursor = end;
    }
    return count;
}

int main(int argc, char **argv) {
    FILE *input = stdin;
    char  line[EDGE_LINE_MAX];
    char  check_text[320];
    int   status;
    long  sequence = 0;
    long  skipped = 0;
    double total_us = 0.0;
    double min_us = 0.0;
    double max_us = 0.0;
    double checksum = 0.0;

    if (argc > 1 && strcmp(argv[1], "-") != 0) {
        input = fopen(argv[1], "r");
        if (input == NULL) {
            fprintf(stderr, "cannot open %s\n", argv[1]);
            return 2;
        }
    }

    printf("# MODEL %s %s fp=%s\n", EDGE_MODEL_FORMAT, edge_model_version(),
           edge_model_fingerprint());
    status = edge_self_check(check_text, sizeof(check_text));
    printf("# %s\n", check_text);
    if (status != 0) {
        fprintf(stderr, "self check failed: %d\n", status);
        return 3;
    }

    /* 全 defaults 向量的一条固定输出：板子开机时也会打同一行，
     * 两边数值相同是"烧进去的模型就是这一份"的最快证据。 */
    {
        float defaults_vector[EDGE_FEATURE_COUNT];
        float probs[EDGE_CLASS_COUNT];
        int   index;
        for (index = 0; index < EDGE_FEATURE_COUNT; ++index) {
            defaults_vector[index] = EDGE_DEFAULTS[index];
        }
        edge_predict_probs(defaults_vector, probs);
        printf("# DEFAULTS_P %.6f\n", (double)probs[1]);
    }
    printf("# READY\n");

    while (fgets(line, (int)sizeof(line), input) != NULL) {
        float  x[EDGE_FEATURE_COUNT];
        float  probs[EDGE_CLASS_COUNT];
        double started;
        double elapsed;
        float  p;
        float  calibrated;

        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r' || line[0] == '\0') {
            continue; /* 注释与空行 */
        }
        if (parse_vector(line, x) != EDGE_FEATURE_COUNT) {
            /* 表头行或残缺行：只跳过，不猜 —— 少一条用例要在 SUMMARY 里看得见。 */
            ++skipped;
            continue;
        }
        ++sequence;

        started = edge_now_us();
        edge_predict_probs(x, probs);
        elapsed = edge_now_us() - started;

        p = probs[1];
        calibrated = edge_calibrate(p);
        checksum += (double)p;

        if (sequence == 1 || elapsed < min_us) {
            min_us = elapsed;
        }
        if (sequence == 1 || elapsed > max_us) {
            max_us = elapsed;
        }
        total_us += elapsed;

        printf("RES %ld %.6f %.6f %.0f\n", sequence, (double)p, (double)calibrated, elapsed);
    }

    printf("# SUMMARY N=%ld SKIP=%ld US_MIN=%.1f US_MAX=%.1f US_MEAN=%.1f CHECKSUM=%.6f\n",
           sequence, skipped, min_us, max_us,
           (sequence > 0) ? total_us / (double)sequence : 0.0, checksum);

    if (input != stdin) {
        fclose(input);
    }
    return 0;
}
