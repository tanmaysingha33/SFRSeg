### The source of this code is: https://github.com/markus-k/bisenetv2-tf2/blob/master/model.py

import tensorflow as tf

import tensorflow.keras.layers as layers
import tensorflow.keras.losses as losses
import tensorflow.keras.metrics as metrics
import tensorflow.keras.models as models
import tensorflow.keras.optimizers as optimizers


# default input shape
INPUT_SHAPE = (512, 1024, 3)


def ge_layer(x_in, c, e=6, stride=1):
    x = layers.Conv2D(filters=c, kernel_size=(3,3), padding='same')(x_in)
    x = layers.BatchNormalization()(x)
    x = layers.Activation('relu')(x)
    
    if stride == 2:
        x = layers.DepthwiseConv2D(depth_multiplier=e, kernel_size=(3,3), strides=2, padding='same')(x)
        x = layers.BatchNormalization()(x)
        
        y = layers.DepthwiseConv2D(depth_multiplier=e, kernel_size=(3,3), strides=2, padding='same')(x_in)
        y = layers.BatchNormalization()(y)
        y = layers.Conv2D(filters=c, kernel_size=(1,1), padding='same')(y)
        y = layers.BatchNormalization()(y)
    else:
        y = x_in
        
    x = layers.DepthwiseConv2D(depth_multiplier=e, kernel_size=(3,3), padding='same')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Conv2D(filters=c, kernel_size=(1,1), padding='same')(x)
    x = layers.BatchNormalization()(x)
    
    x = layers.Add()([x, y])
    x = layers.Activation('relu')(x)
    return x


def stem(x_in, c):
    x = layers.Conv2D(filters=c, kernel_size=(3,3), strides=2, padding='same')(x_in)
    x = layers.BatchNormalization()(x)
    x_split = layers.Activation('relu')(x)
    
    x = layers.Conv2D(filters=c // 2, kernel_size=(1,1), padding='same')(x_split)
    x = layers.BatchNormalization()(x)
    x = layers.Activation('relu')(x)
    
    x = layers.Conv2D(filters=c, kernel_size=(3,3), strides=2, padding='same')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Activation('relu')(x)
    
    y = layers.MaxPooling2D()(x_split)
    
    x = layers.Concatenate()([x, y])
    x = layers.Conv2D(filters=c, kernel_size=(3,3), padding='same')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Activation('relu')(x)
    
    return x


def detail_conv2d(x_in, c, stride=1):
    x = layers.Conv2D(filters=c, kernel_size=(3,3), strides=stride, padding='same')(x_in)
    x = layers.BatchNormalization()(x)
    x = layers.Activation('relu')(x)
    
    return x


def context_embedding(x_in, c):
    x = layers.GlobalAveragePooling2D()(x_in)
    x = layers.BatchNormalization()(x)
    
    x = layers.Reshape((1,1,c))(x)
    
    x = layers.Conv2D(filters=c, kernel_size=(1,1), padding='same')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Activation('relu')(x)
    # broadcasting no needed
    
    x = layers.Add()([x, x_in])
    x = layers.Conv2D(filters=c, kernel_size=(3,3), padding='same')(x)
    return x


def bilateral_guided_aggregation(detail, semantic, c):
    # detail branch
    detail_a = layers.DepthwiseConv2D(kernel_size=(3,3), padding='same')(detail)
    detail_a = layers.BatchNormalization()(detail_a)
    
    detail_a = layers.Conv2D(filters=c, kernel_size=(1,1), padding='same')(detail_a)
    
    detail_b = layers.Conv2D(filters=c, kernel_size=(3,3), strides=2, padding='same')(detail)
    detail_b = layers.BatchNormalization()(detail_b)
    
    detail_b = layers.AveragePooling2D((3,3), strides=2, padding='same')(detail_b)
    
    # semantic branch
    semantic_a = layers.DepthwiseConv2D(kernel_size=(3,3), padding='same')(semantic)
    semantic_a = layers.BatchNormalization()(semantic_a)
    
    semantic_a = layers.Conv2D(filters=c, kernel_size=(1,1), padding='same')(semantic_a)
    semantic_a = layers.Activation('sigmoid')(semantic_a)
    
    semantic_b = layers.Conv2D(filters=c, kernel_size=(3,3), padding='same')(semantic)
    semantic_b = layers.BatchNormalization()(semantic_b)
    
    semantic_b = layers.UpSampling2D((4,4), interpolation='bilinear')(semantic_b)
    semantic_b = layers.Activation('sigmoid')(semantic_b)
    
    # combining
    detail = layers.Multiply()([detail_a, semantic_b])
    semantic = layers.Multiply()([semantic_a, detail_b])
    
    # this layer is not mentioned in the paper !?
    #semantic = layers.UpSampling2D((4,4))(semantic)
    semantic = layers.UpSampling2D((4,4), interpolation='bilinear')(semantic)
    
    x = layers.Add()([detail, semantic])
    x = layers.Conv2D(filters=c, kernel_size=(3,3), padding='same')(x)
    x = layers.BatchNormalization()(x)
    
    return x


def seg_head(x_in, c_t, s, n):
    x = layers.Conv2D(filters=c_t, kernel_size=(3,3), padding='same')(x_in)
    x = layers.BatchNormalization()(x)
    x = layers.Activation('relu')(x)
    
    x = layers.Conv2D(filters=n, kernel_size=(3,3), padding='same')(x)
    x = layers.UpSampling2D((s,s), interpolation='bilinear')(x)
    x = tf.dtypes.cast(x, tf.float32)
    x = tf.keras.activations.softmax(x)
    
    return x


class ArgmaxMeanIOU(metrics.MeanIoU):
    def update_state(self, y_true, y_pred, sample_weight=None):
        return super().update_state(tf.argmax(y_true, axis=-1), tf.argmax(y_pred, axis=-1), sample_weight)


def bisenetv2(num_classes=2, out_scale=8, input_shape=INPUT_SHAPE, l=4, seghead_expand_ratio=2):
    x_in = layers.Input(input_shape)

    # semantic branch
    # S1 + S2
    x = stem(x_in, 64 // l)
    
    # S3
    x = ge_layer(x, 128 // l, stride=2)
    x = ge_layer(x, 128 // l, stride=1)

    # S4
    x = ge_layer(x, 64, stride=2)
    x = ge_layer(x, 64, stride=1)

    # S5
    x = ge_layer(x, 128, stride=2)

    x = ge_layer(x, 128, stride=1)
    x = ge_layer(x, 128, stride=1)
    x = ge_layer(x, 128, stride=1)

    x = context_embedding(x, 128)

    # detail branch
    # S1
    y = detail_conv2d(x_in, 64, stride=2)
    y = detail_conv2d(y, 64, stride=1)

    # S2
    y = detail_conv2d(y, 64, stride=2)
    y = detail_conv2d(y, 64, stride=1)
    y = detail_conv2d(y, 64, stride=1)

    # S3
    y = detail_conv2d(y, 128, stride=2)
    y = detail_conv2d(y, 128, stride=1)
    y = detail_conv2d(y, 128, stride=1)

    x = bilateral_guided_aggregation(y, x, 128)

    x = seg_head(x, num_classes * seghead_expand_ratio, out_scale, num_classes)
    
    model = models.Model(inputs=[x_in], outputs=[x])
    
    # set weight initializers
    """for layer in model.layers:
        if hasattr(layer, 'kernel_initializer'):
            layer.kernel_initializer = tf.keras.initializers.he_uniform()
        if hasattr(layer, 'depthwise_initializer'):
            layer.depthwise_initializer = tf.keras.initializers.he_uniform()"""

    return model


def bisenetv2_compiled(num_classes, decay_steps=10e3, momentum=0.9, weight_decay=0.0005, **kwargs):
    model = bisenetv2(num_classes, **kwargs)

    schedule = optimizers.schedules.PolynomialDecay(
        initial_learning_rate=5e-2,
        decay_steps=decay_steps,
        power=0.9
    )

    try:
        import tensorflow_addons as tfa

        sgd = tfa.optimizers.SGDW(
            weight_decay=weight_decay,
            learning_rate=schedule,
            momentum=momentum,
        )
    except ImportError:
        print('tensorflow_addons not available, not using weight-decay')

        sgd = optimizers.SGD(
            learning_rate=schedule,
            momentum=momentum,
        )

    cce = losses.CategoricalCrossentropy(from_logits=True)

    model.compile(sgd, loss=cce,
                  metrics=['accuracy', ArgmaxMeanIOU(num_classes)]) 
    
    return model


def bisenetv2_output_shape(num_classes, scale, input_shape=INPUT_SHAPE):
    return ((input_shape[0] // 8) * scale, 
            (input_shape[1] // 8) * scale, 
            num_classes)