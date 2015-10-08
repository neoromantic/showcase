shopPassword = 'dreSp8HuSp7S8eDrupre'
crypto = Meteor.npmRequire 'crypto'
bodyParser = Meteor.npmRequire 'body-parser'

Picker.middleware bodyParser.urlencoded({extended: true})

post = Picker.filter (req, res) -> req.method == "POST"

YMController = (params, req, res, next) ->
  YMParams = ["action", "orderSumAmount", "orderSumCurrencyPaycash", "orderSumBankPaycash", "shopId", "invoiceId", "customerNumber"]
  YMRequest = _.pick req.body, YMParams
  YMRequest.md5 = req.body.md5

  YMResponse =
    performedDatetime: (new Date()).toISOString()
    shopId: YMRequest.shopId
    invoiceId: YMRequest.invoiceId
    orderSumAmount: YMRequest.orderSumAmount

  if _.any(YMParams, (key) -> key not of YMRequest)
    YMResponse.code = 200
    YMResponse.message = "Ошибка запроса"
    YMResponse.techMessage = "В параметрах запроса отсутствует необходимый параметр"
  else
    md5check = _.reduce YMParams.reverse(), (str, key) ->
      str = YMRequest[key] + ";" + str
    , shopPassword

    md5sum = crypto.createHash('md5').update(md5check).digest('hex').toUpperCase()

    if md5sum == YMRequest.md5
      YMResponse.code = 0
    else
      YMResponse.code = 1
      YMResponse.message = "Ошибка авторизации"
      YMResponse.techMessage = "MD5-чексумма не совпадает"

  responseAsString = _.reduce _.keys(YMResponse), (str, key) ->
    str + if YMResponse[key] != undefined then "#{key}=\"#{YMResponse[key]}\" " else ""
  , ""
  console.log "response to yandex.money: ", responseAsString
  res.end("<?xml version=\"1.0\" encoding=\"UTF-8\"?><#{YMRequest.action}Response #{responseAsString} />")

post.route '/yandextest/aviso', YMController
post.route '/yandextest/check', YMController

post.route '/yandex/aviso', YMController
post.route '/yandex/check', YMController
