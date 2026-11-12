/*
 * forest_model.h —— 自动生成，请勿手工修改。
 *
 * 生成命令：python tools/edge-export/export_forest.py
 * 模型文件：models/ml-v2-vis3k.json（sha256 前 16 位 = 7a7fc34a92babc78）
 * 参考实现：backend-python/ml/forest.py（端侧语义以它为准）
 *
 * 节点数组只存内部节点，孩子字段编码：
 *     孩子 >= 0  -> 下一层内部节点的绝对下标
 *     孩子 <  0  -> 叶子，叶子下标 = -孩子 - 1
 *
 * 全部数组为 const，放 flash(.rodata)：本机估算 509106 字节（不含代码与字符串）。
 */
#ifndef FOREST_MODEL_H_
#define FOREST_MODEL_H_

#include <stdint.h>

#define EDGE_MODEL_FORMAT          "alc-forest-v1"
#define EDGE_MODEL_VERSION         "ml-v2-vis3k"
#define EDGE_MODEL_FINGERPRINT     "7a7fc34a92babc78"
#define EDGE_FEATURE_COUNT         26
#define EDGE_CLASS_COUNT           2
#define EDGE_TREE_COUNT            100
#define EDGE_NODE_COUNT            24111
#define EDGE_LEAF_COUNT            24211
#define EDGE_CALIB_POINTS          92
#define EDGE_MAX_DEPTH             10
#define EDGE_OPERATING_THRESHOLD   0.3f
#define EDGE_MODEL_BYTES           509106

/* 叶子概率在 float32 下的单次聚合误差量级（导出时量化，不含累加误差）。 */
#define EDGE_QUANT_NOTE            "float32 thresholds + float32 leaf probs"

extern const char *const EDGE_FEATURE_NAMES[EDGE_FEATURE_COUNT];
extern const float       EDGE_DEFAULTS[EDGE_FEATURE_COUNT];
extern const float       EDGE_IMPORTANCE[EDGE_FEATURE_COUNT];
extern const int32_t     EDGE_TREE_ROOT[EDGE_TREE_COUNT];
extern const uint16_t    EDGE_TREE_NODES[EDGE_TREE_COUNT];
extern const float       EDGE_NODE_THRESHOLD[EDGE_NODE_COUNT];
extern const int32_t     EDGE_NODE_LEFT[EDGE_NODE_COUNT];
extern const int32_t     EDGE_NODE_RIGHT[EDGE_NODE_COUNT];
extern const uint8_t     EDGE_NODE_FEATURE[EDGE_NODE_COUNT];
extern const float       EDGE_LEAF_NEG[EDGE_LEAF_COUNT];
extern const float       EDGE_LEAF_POS[EDGE_LEAF_COUNT];
extern const float       EDGE_CALIB_X[EDGE_CALIB_POINTS];
extern const float       EDGE_CALIB_Y[EDGE_CALIB_POINTS];

/* 特征下标常量：让上层代码不用记 0..25 的顺序，改顺序时编译期就会报错。 */
#define EDGE_F_VISM                 0
#define EDGE_F_GUSTMS               1
#define EDGE_F_WINDMS               2
#define EDGE_F_WDIRSIN              3
#define EDGE_F_WDIRCOS              4
#define EDGE_F_TEMPC                5
#define EDGE_F_DEWC                 6
#define EDGE_F_DEWSPREAD            7
#define EDGE_F_CLOUDBASEM           8
#define EDGE_F_QNHHPA               9
#define EDGE_F_VISMIN3H             10
#define EDGE_F_VISMIN6H             11
#define EDGE_F_GUSTMAX3H            12
#define EDGE_F_WINDCHANGE3H         13
#define EDGE_F_QNHTENDENCY3H        14
#define EDGE_F_VISCHANGE3H          15
#define EDGE_F_TEMPTENDENCY3H       16
#define EDGE_F_SPREADTENDENCY3H     17
#define EDGE_F_STATIONCODE          18
#define EDGE_F_HOURSIN              19
#define EDGE_F_HOURCOS              20
#define EDGE_F_MONTH                21
#define EDGE_F_MISS_VIS             22
#define EDGE_F_MISS_GUST            23
#define EDGE_F_MISS_CLOUD           24
#define EDGE_F_MISS_TEMP            25

#endif /* FOREST_MODEL_H_ */
