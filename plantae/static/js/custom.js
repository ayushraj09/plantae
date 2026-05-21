document.addEventListener('DOMContentLoaded', function() {
    // Price slider functionality
    const minRange = document.getElementById('min-range');
    const maxRange = document.getElementById('max-range');
    const sliderRange = document.getElementById('slider-range');
    const currentMin = document.getElementById('current-min');
    const currentMax = document.getElementById('current-max');

    let activeSlider = null;

    function updateSlider() {
        let min = parseInt(minRange.value);
        let max = parseInt(maxRange.value);

        // Ensure values stay within bounds
        if (min < 0) {
            min = 0;
            minRange.value = min;
        }
        if (max > 5000) {
            max = 5000;
            maxRange.value = max;
        }

        // Only apply constraints based on which slider is being moved
        if (activeSlider === 'min') {
            // Min slider is being moved - constrain it only
            if (min > max - 500) {
                min = max - 500;
                minRange.value = min;
            }
        } else if (activeSlider === 'max') {
            // Max slider is being moved - constrain it only
            if (max < min + 500) {
                max = min + 500;
                maxRange.value = max;
            }
        }

        const minPercent = (min / 5000) * 100;
        const maxPercent = (max / 5000) * 100;

        sliderRange.style.left = minPercent + '%';
        sliderRange.style.right = (100 - maxPercent) + '%';

        // Update display values
        currentMin.textContent = min;
        currentMax.textContent = max;
    }

    // Track which slider is being moved
    function handleSliderStart(sliderType) {
        activeSlider = sliderType;
    }

    function handleSliderEnd() {
        activeSlider = null;
    }

    // Event listeners for price slider
    if (minRange && maxRange) {
        minRange.addEventListener('mousedown', () => handleSliderStart('min'));
        minRange.addEventListener('touchstart', () => handleSliderStart('min'));
        minRange.addEventListener('input', updateSlider);
        minRange.addEventListener('mouseup', handleSliderEnd);
        minRange.addEventListener('touchend', handleSliderEnd);

        maxRange.addEventListener('mousedown', () => handleSliderStart('max'));
        maxRange.addEventListener('touchstart', () => handleSliderStart('max'));
        maxRange.addEventListener('input', updateSlider);
        maxRange.addEventListener('mouseup', handleSliderEnd);
        maxRange.addEventListener('touchend', handleSliderEnd);
        
        // Initialize the slider on page load
        updateSlider();
    }

    // Category active state functionality
    const categoryLinks = document.querySelectorAll('.list-menu a');
    const currentPath = window.location.pathname;
    const currentParams = new URLSearchParams(window.location.search);

    function setActiveCategory() {
        categoryLinks.forEach(link => {
            // Remove active class from all links first
            link.classList.remove('active');
            
            // Parse the link URL to get path and parameters
            const linkUrl = new URL(link.href);
            const linkPath = linkUrl.pathname;
            const linkParams = new URLSearchParams(linkUrl.search);
            
            // Check if paths match
            if (linkPath === currentPath) {
                // For category links, check if the category parameter matches
                const linkCategory = linkParams.get('category');
                const currentCategory = currentParams.get('category');
                
                // If both have category parameters and they match, or both don't have category parameters
                if (linkCategory === currentCategory) {
                    link.classList.add('active');
                } else if (!linkCategory && !currentCategory) {
                    // This is the "All products" link and no category is selected
                    link.classList.add('active');
                }
            }
        });
    }

    // Set active category on page load
    setActiveCategory();

    // Apply filter function for Django integration
    window.applyPriceFilter = function() {
        const minPrice = minRange.value;
        const maxPrice = maxRange.value;
        
        // Get current URL parameters
        const urlParams = new URLSearchParams(window.location.search);
        urlParams.set('min_price', minPrice);
        urlParams.set('max_price', maxPrice);
        
        // Redirect with new parameters
        window.location.href = window.location.pathname + '?' + urlParams.toString();
    };
});