function DisableOnSubmit(element) {
    this.element = element
}

DisableOnSubmit.prototype.init = function () {
    this.element.addEventListener("submit", this.disableSubmit.bind(this))
}

DisableOnSubmit.prototype.disableSubmit = function () {
    var submitElements = this.element.querySelectorAll("input[type=submit]")
    for (var i = 0; i < submitElements.length; i++) {
        submitElements[i].disabled = true
        
        if (submitElements[i].classList.contains("disable-permanently") === false) {
            setTimeout(this.reenableSubmit.bind(submitElements[i]), 10000)
        }
    }
    return false
}

DisableOnSubmit.prototype.reenableSubmit = function () {
    this.disabled = false
}

if ('addEventListener' in document) {
    document.addEventListener("DOMContentLoaded", function () {
        var elements = document.querySelectorAll("[data-module~=disable-on-submit]")
        for (var i = 0; i < elements.length; i++) {
            new DisableOnSubmit(elements[i]).init()
        }
    })
}