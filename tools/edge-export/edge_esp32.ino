/*
 * edge_esp32.ino —— 端侧推理固件（ESP32 / Arduino 框架）
 *
 * 作用：把**同一份** edge_infer.c 跑在真板子上，从串口按行收 26 个浮点数，
 * 逐行回 p 与单次耗时，最后打汇总。pair_check.py 认的就是这个文本协议。
 *
 * 协议（与 edge_x86_main.c 完全一致，两个宿主可以互换）
 * ---------------------------------------------------
 * 开机：   # MODEL <format> <version> fp=<指纹>
 *          # model=... trees=... features=... nodes=... leaves=... calib=... bytes=... checks=OK
 *          # READY
 * 每行：   RES <seq> <p:6位小数> <p_cal:6位小数> <us>
 * 汇总：   # SUMMARY N=<n> SKIP=<k> US_MIN=<a> US_MAX=<b> US_MEAN=<c> CHECKSUM=<s>
 *
 * 为什么不用 String：1000 行数据下 `String` 会在堆上反复申请释放，
 * 长时间跑必然碎片化，最后表现成"偶发丢行"。这里用定长缓冲，一个字节都不 malloc。
 *
 * 编译要点（详见 README-运行步骤.md）
 * ----------------------------------
 * 1. 本文件与 forest_model.c/.h、edge_infer.c/.h 放在**同一个目录**，
 *    Arduino 会把该目录下所有 .c/.cpp 一起编译。
 * 2. 模型数组约 497 KiB，全在 .rodata（flash）。默认分区表只有 1310 KiB 给 app，
 *    足够但要留余量，建议用 `PartitionScheme=huge_app`（3 MiB app）。
 * 3. 波特率 921600：26 个浮点数一行约 190 字节，115200 下 1000 行要 20 秒以上，
 *    921600 下压到 3 秒内，且 CH340 支持。
 */
#include <stdlib.h>
#include <string.h>

#include "edge_infer.h"

/* ---------------------------------------------------------------- 可调参数 */

#define EDGE_BAUD             921600  /* 与 pair_check.py --baud 保持一致 */
#define EDGE_LINE_MAX         512     /* 26 个数 × 最多 12 字符 + 分隔符，512 足够 */
#define EDGE_SUMMARY_EVERY    1000    /* 攒够这么多条就打一次汇总 */
#define EDGE_PROGRESS_EVERY   100     /* 每 100 条打一行进度，便于现场看门狗 */

/* ---------------------------------------------------------------- 运行状态 */

static char     g_line[EDGE_LINE_MAX];
static size_t   g_line_len = 0;

static uint32_t g_count = 0;        /* 已成功推理条数 */
static uint32_t g_skipped = 0;      /* 解析失败的条数（表头、残缺行） */
static uint32_t g_min_us = 0;
static uint32_t g_max_us = 0;
static uint64_t g_total_us = 0;
static double   g_checksum = 0.0;   /* p 的累加和：两端对不上说明有丢行/错行 */

/* ---------------------------------------------------------------- 串口输出 */

/** 打印 p（6 位小数）而不用 printf 的 %f：有的内核配置把浮点 printf 关掉了，
 *  这里自己拼，保证任何 Arduino 内核配置下输出格式都一样。 */
static void print_fixed6(double value) {
    uint32_t scaled;
    if (value < 0.0) {
        Serial.print('-');
        value = -value;
    }
    if (value > 999.999999) {
        value = 999.999999; /* 概率不会超过 1，纯防御 */
    }
    scaled = (uint32_t)(value * 1000000.0 + 0.5);
    Serial.print((uint32_t)(scaled / 1000000u));
    Serial.print('.');
    {
        uint32_t fraction = scaled % 1000000u;
        uint32_t divisor = 100000u;
        while (divisor > 0u) {
            Serial.print((uint32_t)(fraction / divisor));
            fraction %= divisor;
            divisor /= 10u;
        }
    }
}

static void print_summary(void) {
    Serial.print("# SUMMARY N=");
    Serial.print(g_count);
    Serial.print(" SKIP=");
    Serial.print(g_skipped);
    Serial.print(" US_MIN=");
    Serial.print(g_min_us);
    Serial.print(" US_MAX=");
    Serial.print(g_max_us);
    Serial.print(" US_MEAN=");
    Serial.print((g_count > 0u) ? (double)g_total_us / (double)g_count : 0.0, 1);
    Serial.print(" CHECKSUM=");
    Serial.println(g_checksum, 6);
}

/* ---------------------------------------------------------------- 解析与推理 */

/** 从一行里读出 26 个数；返回读到的个数。分隔符允许空格、逗号、制表符。 */
static int parse_vector(const char *line, float *x) {
    const char *cursor = line;
    int count = 0;
    while (count < EDGE_FEATURE_COUNT) {
        char *end = NULL;
        double value;
        while (*cursor == ' ' || *cursor == '\t' || *cursor == ',' || *cursor == ';') {
            ++cursor;
        }
        if (*cursor == '\0' || *cursor == '\r' || *cursor == '\n') {
            break;
        }
        value = strtod(cursor, &end);
        if (end == cursor) {
            break; /* 不是数字：这行作废，不猜 */
        }
        /* 端侧只有 float32：这里显式截断，与云端"把用例量化到 float32"是同一件事。 */
        x[count++] = (float)value;
        cursor = end;
    }
    return count;
}

static void handle_line(char *line) {
    float    x[EDGE_FEATURE_COUNT];
    float    probs[EDGE_CLASS_COUNT];
    uint32_t started;
    uint32_t elapsed;

    if (line[0] == '\0' || line[0] == '#') {
        return; /* 空行或注释（表头也会落到这里，parse 失败同样跳过） */
    }
    if (parse_vector(line, x) != EDGE_FEATURE_COUNT) {
        ++g_skipped;
        return;
    }

    started = micros();
    edge_predict_probs(x, probs);
    elapsed = micros() - started;

    ++g_count;
    g_total_us += elapsed;
    if (g_count == 1u || elapsed < g_min_us) {
        g_min_us = elapsed;
    }
    if (g_count == 1u || elapsed > g_max_us) {
        g_max_us = elapsed;
    }
    g_checksum += (double)probs[1];

    Serial.print("RES ");
    Serial.print(g_count);
    Serial.print(' ');
    print_fixed6((double)probs[1]);
    Serial.print(' ');
    print_fixed6((double)edge_calibrate(probs[1]));
    Serial.print(' ');
    Serial.println(elapsed);

    if (g_count % EDGE_PROGRESS_EVERY == 0u) {
        Serial.print("# PROGRESS ");
        Serial.println(g_count);
    }
    /* 收满 N 条打汇总，然后把计数器归零，方便现场连着跑第二轮 */
    if (g_count >= EDGE_SUMMARY_EVERY) {
        print_summary();
        g_count = 0u;
        g_skipped = 0u;
        g_total_us = 0u;
        g_min_us = 0u;
        g_max_us = 0u;
        g_checksum = 0.0;
    }
}

/* ---------------------------------------------------------------- 生命周期 */

void setup() {
    char check_text[320];
    int  status;

    Serial.begin(EDGE_BAUD);
    delay(200); /* USB-CDC 之外的板子（CH340）需要一点时间让上位机打开串口 */

    Serial.print("# MODEL ");
    Serial.print(EDGE_MODEL_FORMAT);
    Serial.print(' ');
    Serial.print(edge_model_version());
    Serial.print(" fp=");
    Serial.println(edge_model_fingerprint());

    status = edge_self_check(check_text, sizeof(check_text));
    Serial.print("# ");
    Serial.println(check_text);

    /* 开机把"当前这条向量"也跑一遍：既能看出模型有没有被编译器优化掉，
     * 也给出一份"两端都应相同的固定输出"（defaults 全填 + 单次 predict）。 */
    {
        float  defaults_vector[EDGE_FEATURE_COUNT];
        float  probs[EDGE_CLASS_COUNT];
        int    index;
        for (index = 0; index < EDGE_FEATURE_COUNT; ++index) {
            defaults_vector[index] = EDGE_DEFAULTS[index];
        }
        edge_predict_probs(defaults_vector, probs);
        Serial.print("# DEFAULTS_P ");
        print_fixed6((double)probs[1]);
        Serial.println();
    }

    if (status != EDGE_CHECK_OK) {
        /* 自检不过就不要接收用例：跑出来的 p 不可信，宁可显式停在这里 */
        Serial.println("# SELF_CHECK_FAILED 拒绝进入对拍模式");
        while (true) {
            delay(1000);
        }
    }
    Serial.println("# READY");
}

void loop() {
    while (Serial.available() > 0) {
        const int ch = Serial.read();
        if (ch < 0) {
            break;
        }
        if (ch == '\r') {
            continue; /* 兼容 CRLF */
        }
        if (ch == '\n') {
            g_line[g_line_len] = '\0';
            handle_line(g_line);
            g_line_len = 0;
            continue;
        }
        if (g_line_len + 1 < EDGE_LINE_MAX) {
            g_line[g_line_len++] = (char)ch;
        } else {
            g_line_len = 0; /* 超长行直接丢弃，绝不越界写 */
            ++g_skipped;
        }
    }
}
