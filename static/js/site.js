document.addEventListener("DOMContentLoaded", function () {
    const pickers = document.querySelectorAll("[data-variant-picker]");

    pickers.forEach(function (picker) {
        const colourButtons = picker.querySelectorAll(".colour-swatch");
        const sizeButtons = picker.querySelectorAll("[data-size-option]");
        const selectedColour = picker.querySelector("[data-selected-colour]");
        const selectedSize = picker.querySelector("[data-selected-size]");
        const stockMessage = picker.querySelector("[data-stock-message]");
        const variantInput = picker.querySelector("[data-variant-input]");

        function chooseColour(colour) {
            colourButtons.forEach(function (button) {
                const selected = button.dataset.colour === colour;

                button.classList.toggle("is-selected", selected);
                button.setAttribute("aria-pressed", String(selected));
            });

            sizeButtons.forEach(function (button) {
                const matchesColour = button.dataset.colour === colour;

                button.hidden = !matchesColour;
                button.classList.remove("is-selected");
                button.setAttribute("aria-pressed", "false");
            });

            selectedColour.textContent = colour;
            selectedSize.textContent = "";
            stockMessage.textContent = "Choose a size";
            variantInput.value = "";
        }

        colourButtons.forEach(function (button) {
            button.addEventListener("click", function () {
                chooseColour(button.dataset.colour);
            });
        });

        sizeButtons.forEach(function (button) {
            button.addEventListener("click", function () {
                sizeButtons.forEach(function (otherButton) {
                    otherButton.classList.remove("is-selected");
                    otherButton.setAttribute("aria-pressed", "false");
                });

                button.classList.add("is-selected");
                button.setAttribute("aria-pressed", "true");

                selectedSize.textContent = button.dataset.size;
                stockMessage.textContent =
                    button.dataset.stock + " owned — check your rental dates";
                variantInput.value = button.dataset.variantId;
            });
        });

        const savedVariant = Array.from(sizeButtons).find(
            button => button.dataset.variantId === variantInput.value
        );

        if (savedVariant) {
            chooseColour(savedVariant.dataset.colour);
            savedVariant.click();
        } else if (picker.dataset.defaultColour) {
            chooseColour(picker.dataset.defaultColour);
        }

        const rentalForm = picker.closest("[data-rental-form]");
        const rentalResult = rentalForm?.querySelector("[data-rental-result]");

        if (rentalForm && rentalResult) {
            const hidePreviousResult = () => {
                rentalResult.hidden = true;
            };

            rentalForm.addEventListener("input", hidePreviousResult);
            rentalForm.addEventListener("change", hidePreviousResult);

            picker.addEventListener("click", event => {
                if (event.target.closest(".colour-swatch, [data-size-option]")) {
                    hidePreviousResult();
                }
            });
        }
    });
});
