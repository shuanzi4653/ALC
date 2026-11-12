/*
 * edge_infer.c —— 端侧推理实现（纯 C99）
 *
 * 三个硬约束，任何一条破了这个文件就不该合并：
 *   1. 无递归          —— 树遍历是一个 while 循环，栈用量与树高无关（只有 3 个局部量）。
 *   2. 无动态内存      —— 没有 malloc/free/new，也没有变长数组；数组全是 forest_model.c 里的 const。
 *   3. 无 stdio / 无 libm 依赖 —— 自检文本是自己拼的，不 snprintf，这样同一份代码在
 *                         ESP32、x86 上行为完全一致，也便于在只有 8 KB 栈的任务里跑。
 *
 * 数值口径：全程 float32（与 ESP32 的 FPU 一致），运算顺序与 forest.py 逐行对应。
 * 顺序之所以重要：浮点加法不满足结合律，先累加 NEG 还是先累加 POS 会差几个 ulp。
 * 这里固定为"先 0 后 1"，与 Python 的 `for i, c in enumerate(counts)` 一致。
 */
#include "edge_infer.h"

/* ------------------------------------------------------------------ 小工具 */

/** 判断 float32 是否为有限值：不引 math.h，嵌入式上也少一个依赖。 */
static int edge_is_finite(float value) {
    /* NaN 自身不相等；float32 的有限上界是 3.402823466e38。 */
    if (value != value) {
        return 0;
    }
    if (value > 3.402823466e38f || value < -3.402823466e38f) {
        return 0;
    }
    return 1;
}

/** 极简文本拼接缓冲：只做上报，不参与任何数值计算。 */
typedef struct {
    char  *buffer;
    size_t capacity;
    size_t length;
} edge_text_t;

static void edge_text_init(edge_text_t *text, char *buffer, size_t capacity) {
    text->buffer = buffer;
    text->capacity = capacity;
    text->length = 0;
    if (buffer != 0 && capacity > 0) {
        buffer[0] = '\0';
    }
}

static void edge_text_char(edge_text_t *text, char ch) {
    if (text->buffer == 0 || text->capacity == 0) {
        return;
    }
    if (text->length + 1 >= text->capacity) {
        return; /* 截断而不是溢出：宁可少打几个字，不能写坏内存 */
    }
    text->buffer[text->length++] = ch;
    text->buffer[text->length] = '\0';
}

static void edge_text_str(edge_text_t *text, const char *value) {
    while (value != 0 && *value != '\0') {
        edge_text_char(text, *value++);
    }
}

static void edge_text_uint(edge_text_t *text, uint32_t value) {
    char digits[11];
    int  count = 0;
    if (value == 0u) {
        edge_text_char(text, '0');
        return;
    }
    while (value > 0u && count < 11) {
        digits[count++] = (char)('0' + (value % 10u));
        value /= 10u;
    }
    while (count-- > 0) {
        edge_text_char(text, digits[count]);
    }
}

/* ------------------------------------------------------------------ 单棵树 */

/**
 * 从根下降到叶子，返回叶子下标。
 *
 * 关键性质：展平时每个节点的孩子引用都指向"后创建"的节点（严格大于父下标），
 * 叶子用负引用表示，所以这个循环一定会终止 —— 不需要深度计数器兜底，
 * 也不存在模型被写坏后死循环的可能（写坏会在 edge_self_check 里先被拦下）。
 */
static int32_t edge_leaf_of(const float x[EDGE_FEATURE_COUNT], int32_t root) {
    int32_t ref = root;
    while (ref >= 0) {
        const uint8_t feature = EDGE_NODE_FEATURE[ref];
        const float   value = x[feature];
        /* forest.py: `vector[idx] <= thr` 走 left，否则 right。等于阈值走左边，不许改成 <。 */
        ref = (value <= EDGE_NODE_THRESHOLD[ref]) ? EDGE_NODE_LEFT[ref] : EDGE_NODE_RIGHT[ref];
    }
    return -ref - 1;
}

/* ------------------------------------------------------------------ 对外接口 */

void edge_predict_probs(const float x[EDGE_FEATURE_COUNT], float probs[EDGE_CLASS_COUNT]) {
    float totals[EDGE_CLASS_COUNT];
    int   tree;
    int   index;

    for (index = 0; index < EDGE_CLASS_COUNT; ++index) {
        totals[index] = 0.0f;
    }

    for (tree = 0; tree < EDGE_TREE_COUNT; ++tree) {
        const int32_t leaf = edge_leaf_of(x, EDGE_TREE_ROOT[tree]);
        const float   count_neg = EDGE_LEAF_NEG[leaf];
        const float   count_pos = EDGE_LEAF_POS[leaf];
        const float   total = count_neg + count_pos;

        /* forest.py: `if total <= 0: continue` —— 空叶子跳过，不贡献 0/0。 */
        if (total <= 0.0f) {
            continue;
        }
        totals[0] += count_neg / total;
        totals[1] += count_pos / total;
    }

    /* forest.py: `grand = sum(totals) or 1.0`，即总和为 0 时退化成 1.0（Python 的 or 语义）。 */
    {
        float grand = totals[0] + totals[1];
        if (grand == 0.0f) {
            grand = 1.0f;
        }
        probs[0] = totals[0] / grand;
        probs[1] = totals[1] / grand;
    }
}

float edge_predict(const float x[EDGE_FEATURE_COUNT]) {
    float probs[EDGE_CLASS_COUNT];
    edge_predict_probs(x, probs);
    return probs[1];
}

const char *edge_predict_level(const float x[EDGE_FEATURE_COUNT]) {
    float probs[EDGE_CLASS_COUNT];
    edge_predict_probs(x, probs);
    /* 严格大于才算 POS：并列时更"保守"地报 NEG，与 Python max() 取首个最大值同解。 */
    return (probs[1] > probs[0]) ? "POS" : "NEG";
}

float edge_calibrate(float raw) {
#if EDGE_CALIB_POINTS > 0
    int i;
    if (raw <= EDGE_CALIB_X[0]) {
        return EDGE_CALIB_Y[0];
    }
    if (raw >= EDGE_CALIB_X[EDGE_CALIB_POINTS - 1]) {
        return EDGE_CALIB_Y[EDGE_CALIB_POINTS - 1];
    }
    /* 线性扫描而不是二分：92 个点、一次推理一次，速度不是瓶颈；
     * 保持与 nowcast._interp 完全相同的比较顺序，才不会在"等于断点"的边界上分叉。 */
    for (i = 1; i < EDGE_CALIB_POINTS; ++i) {
        if (raw <= EDGE_CALIB_X[i]) {
            const float span = EDGE_CALIB_X[i] - EDGE_CALIB_X[i - 1];
            if (span <= 0.0f) {
                return EDGE_CALIB_Y[i];
            }
            {
                const float ratio = (raw - EDGE_CALIB_X[i - 1]) / span;
                return EDGE_CALIB_Y[i - 1] + ratio * (EDGE_CALIB_Y[i] - EDGE_CALIB_Y[i - 1]);
            }
        }
    }
    return EDGE_CALIB_Y[EDGE_CALIB_POINTS - 1];
#else
    return raw;
#endif
}

int edge_self_check(char *buffer, size_t size) {
    edge_text_t text;
    int32_t     index;
    int         status = EDGE_CHECK_OK;

    edge_text_init(&text, buffer, size);

    /* 1) 节点表：特征下标在范围内、孩子引用有效且递增、阈值有限。 */
    for (index = 0; index < (int32_t)EDGE_NODE_COUNT; ++index) {
        const int32_t left = EDGE_NODE_LEFT[index];
        const int32_t right = EDGE_NODE_RIGHT[index];

        if ((int32_t)EDGE_NODE_FEATURE[index] >= EDGE_FEATURE_COUNT) {
            status = EDGE_CHECK_BAD_FEATURE_INDEX;
            break;
        }
        if (!edge_is_finite(EDGE_NODE_THRESHOLD[index])) {
            status = EDGE_CHECK_BAD_THRESHOLD;
            break;
        }
        if (left == 0 || right == 0) { /* 下标 0 只能是某棵树的根，不可能当孩子 */
            status = EDGE_CHECK_BAD_CHILD_INDEX;
            break;
        }
        /* 叶子引用（负值）必须落在叶子表内。 */
        if (left < 0 && (-left - 1) >= (int32_t)EDGE_LEAF_COUNT) {
            status = EDGE_CHECK_BAD_CHILD_INDEX;
            break;
        }
        if (right < 0 && (-right - 1) >= (int32_t)EDGE_LEAF_COUNT) {
            status = EDGE_CHECK_BAD_CHILD_INDEX;
            break;
        }
        /* 内部节点孩子必须排在父之后：这条保证了遍历必然终止，也证明展平顺序没写反。 */
        if ((left > 0 && left <= index) || (right > 0 && right <= index)) {
            status = EDGE_CHECK_BAD_CHILD_ORDER;
            break;
        }
    }

    /* 2) 叶子表：每片叶子的计数有限且和为正（否则 forest.py 会 continue，端侧也必须能跳过）。 */
    if (status == EDGE_CHECK_OK) {
        for (index = 0; index < (int32_t)EDGE_LEAF_COUNT; ++index) {
            const float neg = EDGE_LEAF_NEG[index];
            const float pos = EDGE_LEAF_POS[index];
            if (!edge_is_finite(neg) || !edge_is_finite(pos) || (neg + pos) <= 0.0f) {
                status = EDGE_CHECK_BAD_LEAF;
                break;
            }
        }
    }

    /* 3) 校准表：x 必须非降且有限（插值要在单调区间上做）。 */
    if (status == EDGE_CHECK_OK) {
        for (index = 0; index < (int32_t)EDGE_CALIB_POINTS; ++index) {
            if (!edge_is_finite(EDGE_CALIB_X[index]) || !edge_is_finite(EDGE_CALIB_Y[index])) {
                status = EDGE_CHECK_BAD_CALIB;
                break;
            }
            if (index > 0 && EDGE_CALIB_X[index] < EDGE_CALIB_X[index - 1]) {
                status = EDGE_CHECK_BAD_CALIB;
                break;
            }
        }
    }

    edge_text_str(&text, "model=");
    edge_text_str(&text, EDGE_MODEL_VERSION);
    edge_text_str(&text, " fp=");
    edge_text_str(&text, EDGE_MODEL_FINGERPRINT);
    edge_text_str(&text, " trees=");
    edge_text_uint(&text, (uint32_t)EDGE_TREE_COUNT);
    edge_text_str(&text, " features=");
    edge_text_uint(&text, (uint32_t)EDGE_FEATURE_COUNT);
    edge_text_str(&text, " nodes=");
    edge_text_uint(&text, (uint32_t)EDGE_NODE_COUNT);
    edge_text_str(&text, " leaves=");
    edge_text_uint(&text, (uint32_t)EDGE_LEAF_COUNT);
    edge_text_str(&text, " calib=");
    edge_text_uint(&text, (uint32_t)EDGE_CALIB_POINTS);
    edge_text_str(&text, " bytes=");
    edge_text_uint(&text, (uint32_t)EDGE_MODEL_BYTES);
    edge_text_str(&text, " checks=");
    edge_text_str(&text, (status == EDGE_CHECK_OK) ? "OK" : "ERR");
    if (status != EDGE_CHECK_OK) {
        edge_text_str(&text, " code=");
        edge_text_char(&text, '-');
        edge_text_uint(&text, (uint32_t)(-status));
    }
    return status;
}

uint32_t edge_model_bytes(void) {
    return (uint32_t)EDGE_MODEL_BYTES;
}

const char *edge_model_version(void) {
    return EDGE_MODEL_VERSION;
}

const char *edge_model_fingerprint(void) {
    return EDGE_MODEL_FINGERPRINT;
}
