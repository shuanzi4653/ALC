/*
 * edge_infer.h —— 端侧推理接口（纯 C99，无动态内存、无递归、无 stdio 依赖）
 *
 * 语义基准：backend-python/ml/forest.py 的 Forest.predict()
 *   - 每棵树按叶子值做 c/total 归一后累加；
 *   - 100 棵树累加完再统一除以总和（grand）得到概率；
 *   - argmax 取"首个最大值"（probs[1] > probs[0] 才判 POS，并列时判 NEG）。
 * 只要这三条有任何一条改动，端云对拍就会掉到 1e-4 以外 —— 所以这三条写在注释里，
 * 也写在 `端侧对拍-实验报告.md` 的"口径"一节。
 *
 * 输入向量的 26 个分量必须已经按 `backend-python/ml/nowcast.py` 的 FEATURES 顺序排好，
 * 缺失值在主控侧就已填成模型 defaults（见 forest_model.h 的 EDGE_DEFAULTS）。
 * 端侧不做缺省填充：它拿到的是一条已经填好的定长向量，这样"填了没填"这件事
 * 只在一个地方发生，不会出现端云各填一套的情况。
 */
#ifndef EDGE_INFER_H_
#define EDGE_INFER_H_

#include <stddef.h>
#include <stdint.h>

#include "forest_model.h"

#ifdef __cplusplus
extern "C" {
#endif

/* 自检返回码：0 = 全部通过。 */
#define EDGE_CHECK_OK                  0
#define EDGE_CHECK_BAD_FEATURE_INDEX  -1
#define EDGE_CHECK_BAD_CHILD_INDEX    -2
#define EDGE_CHECK_BAD_CHILD_ORDER    -3
#define EDGE_CHECK_BAD_LEAF           -4
#define EDGE_CHECK_BAD_CALIB          -5
#define EDGE_CHECK_BAD_THRESHOLD      -6

/**
 * 端侧主推理入口。
 *
 * @param x 26 维特征（float32），顺序同 EDGE_FEATURE_NAMES。
 * @return 类别 POS 的概率（低能见度 <3000 m 的概率），范围 [0,1]。
 *         该值是**未校准**的森林原始概率，与 forest.py 的 probabilitiesExact.POS 逐字对应。
 */
float edge_predict(const float x[EDGE_FEATURE_COUNT]);

/**
 * 同时拿到两类概率。probs[0] = NEG，probs[1] = POS。
 * 两者之和恒为 1（浮点误差内），因为 forest.py 最后也做了一次 grand 归一。
 */
void edge_predict_probs(const float x[EDGE_FEATURE_COUNT], float probs[EDGE_CLASS_COUNT]);

/**
 * 概率最大类的名字（"POS" / "NEG"）。并列时返回 "NEG"，与 Python 的 max() 取首个最大值一致。
 */
const char *edge_predict_level(const float x[EDGE_FEATURE_COUNT]);

/**
 * isotonic 校准曲线插值，语义与 backend-python/ml/nowcast.py 的 _interp() 一致：
 * 越界取端点，中间线性插值，跨度 <= 0 时取右端点。
 *
 * 注意：forest.py 的 predict() **不**做校准，所以对拍的主指标是 edge_predict 的原始概率。
 * 这个函数是为了"端侧也能复现 nowcast 的 calibrated 概率"而随附的，单独对拍
 * （pair_check.py 的 --calibrated 指标）。
 */
float edge_calibrate(float raw);

/**
 * 模型自检：数组长度、孩子下标范围与单调性（孩子必须排在父之后）、叶子概率、
 * 阈值与校准表的有限性。开机时调用一次，把结果打进串口 —— 板子上跑的是不是
 * 同一份模型，靠的就是这个和指纹。
 *
 * @param buffer 输出文本缓冲（建议 >= 256 字节），可为 NULL（只做检查不输出）。
 * @param size   缓冲区大小。
 * @return 0 表示通过，负数为 EDGE_CHECK_* 错误码。
 */
int edge_self_check(char *buffer, size_t size);

/** 模型数组占用的 flash 字节数（编译期常量，不是实测堆占用）。 */
uint32_t edge_model_bytes(void);

/** 模型版本 / 指纹字符串（指纹是模型 JSON 的 sha256 前 16 位）。 */
const char *edge_model_version(void);
const char *edge_model_fingerprint(void);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* EDGE_INFER_H_ */
