# AstrBot 梗图抽象猜词插件

这是一个基于 AstrBot 的梗图抽象猜词插件，支持发送图片题目并校验答案。

## 指令

- `/梗图` 或 `/gengtu` 或 `/抽象猜词`：获取最新题目图片
- `/答案 你的答案`：提交答案并校验结果

## 接口使用

- 请到 [柠柚API](https://api.nycnm.cn) 注册获取 API 密钥
- 密钥需要在插件配置中填写
- 接口请求需要包含 `apikey` 参数，值为注册获取的密钥
- 如有问题或建议，加入QQ群：593347084

## 返回示例

题目接口：`https://api.nycnm.cn/API/gengtu.php?apikey=`

```
{
  "success": true,
  "code": 200,
  "message": "获取成功",
  "data": {
    "question": {
      "id": 8,
      "image": "https://sns-img-hw.xhscdn.com/.../format/jpg",
      "answer": "六六大顺"
    },
    "show_answer": true,
    "api": "柠柚API 仅供娱乐 https://api.nycnm.cn"
  }
}
```

校验接口：`https://api.nycnm.cn/API/gengtu.php?check=8&answer=六六大顺&apikey=`

```
{
  "success": true,
  "code": 200,
  "message": "回答正确！",
  "data": {
    "correct": true,
    "correct_answer": "六六大顺"
  }
}
```

## 配置

在 `_conf_schema.json` 中可配置：
- `api_url` 接口地址
- `api_key` API 密钥
- `timeout` 请求超时

## 许可证

本插件遵循 MIT 许可证。