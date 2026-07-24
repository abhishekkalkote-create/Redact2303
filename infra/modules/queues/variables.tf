variable "name" {
  type = string
}

variable "visibility_timeout_seconds" {
  description = "Per queue type — OCR/detect jobs run far longer than intake/export."
  type        = map(number)
  default = {
    intake          = 120
    extract         = 300
    detect          = 600
    export          = 180
    verify          = 60
    rule_extraction = 300
  }
}

variable "tags" {
  type    = map(string)
  default = {}
}
